"""Mode-driven website policy, isolated from desktop and timer enforcement."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import threading
import time
from omarchy_kids.core.paths import write_public
from . import websites_setup as setup


class AssetServer:
    """Serve exactly two public installation assets on IPv4 loopback."""
    def __init__(self, directory, port=setup.PORT):
        assets = {"/school.crx": ("application/x-chrome-extension", (directory / "school.crx").read_bytes()),
                  "/update.xml": ("application/xml", (directory / "update.xml").read_bytes())}

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def do_GET(self):
                # Chrome appends update metadata to the XML request. No query
                # value is interpreted, reflected or used as a filesystem path.
                path = self.path.split("?", 1)[0]
                if path not in assets:
                    self.send_error(404)
                    return
                kind, data = assets[path]
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_):
                pass

        self.server = HTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Websites:
    def __init__(self, school):
        self.school = school
        layout = school.host.layout
        self.config_dir = layout.config_path.parent
        self.directory = layout.state_dir.parent / "school-websites"
        self.etc = setup.ETC if layout.mode == "system" else self.config_dir / "browser-etc"
        self.asset_server = None
        self.error = ""
        self.clients = {}
        self.domains = []
        self.enabled = False
        self.generation = ""
        self.extension_id = ""
        self.version = ""
        self.last_conflict_check = -100
        self.conflicts = []

    def ready(self):
        try:
            receipt = setup.read_json(self.config_dir / "school-websites.json")
            identity = setup.read_json(self.directory / "installation.json")
            extension_id = receipt.get("extension_id", "")
            if receipt.get("identity") != setup.HOST or not re.fullmatch(r"[a-p]{32}", extension_id):
                return False
            if identity.get("extension_id") != extension_id:
                return False
            self.extension_id, self.version = extension_id, identity["version"]
            return all(p.is_file() and not p.is_symlink() for p in setup.policy_paths(self.etc) + setup.host_paths(self.etc))
        except (OSError, ValueError, KeyError):
            return False

    def preflight(self):
        if not self.ready():
            raise ValueError("Run the updated School Mode setup for this account before enabling websites.")
        conflicts = setup.conflicts(self.etc, self.extension_id)
        if conflicts:
            raise ValueError(conflicts[0])
        if self.asset_server is None:
            try:
                self.asset_server = AssetServer(self.directory)
            except OSError as error:
                raise ValueError(f"The local browser installer could not start on port {setup.PORT}. Rerun setup or resolve the port conflict.") from error

    def reconcile(self, now):
        domains = set()
        enabled = False
        for uid in self.school.managed_uids():
            profile = self.school.policy_for(uid).profile
            if not profile["websites_enabled"]:
                continue
            enabled = True
            if self.school.snapshot(uid, now).get("mode") == "school":
                domains.update(profile["school_blocked_domains"])
        self.enabled, self.domains = enabled, sorted(domains)
        self.generation = hashlib.sha256(json.dumps([enabled, self.domains]).encode()).hexdigest()
        self.error = ""
        if not self.ready():
            if enabled:
                self.error = "Website setup is missing. Rerun the updated School Mode setup."
            return
        try:
            if enabled:
                if self.asset_server is None:
                    try:
                        self.preflight()
                    except ValueError as error:
                        # A failed updater is not a reason to retain stale
                        # School policies in Free Time. Existing companions
                        # can still receive rules over the native connection.
                        self.error = str(error)
                if time.monotonic() - self.last_conflict_check >= 5:
                    self.conflicts = setup.conflicts(self.etc, self.extension_id)
                    self.last_conflict_check = time.monotonic()
                if self.conflicts:
                    # Report a policy added after enrollment, but still remove
                    # our School-only block list when Free Time starts. Never
                    # leave old School restrictions behind because of a conflict.
                    self.error = self.error or self.conflicts[0]
            policy = {}
            if enabled:
                policy = {"ExtensionSettings": {self.extension_id: setup.extension_settings()},
                          "3rdparty": setup.managed_flag(self.extension_id)}
                if self.domains:
                    policy["URLBlocklist"] = self.domains
            text = json.dumps(policy, indent=2) + "\n"
            for path in setup.policy_paths(self.etc):
                setup.owned(path)
                current = path.read_text()
                setup.validate_policy(json.loads(current), self.extension_id)
                if current != text:
                    write_public(path, text)
        except (OSError, ValueError) as error:
            self.error = str(error)

    def wire_status(self):
        # Domains and a digest are public policy, never passwords or browsing history.
        return {"ok": True, "enabled": self.enabled, "domains": list(self.domains),
                "generation": self.generation, "version": self.version}

    def acknowledge(self, uid, message):
        generation, instance = message.get("generation"), message.get("instance")
        error = message.get("error", "")
        if (generation != self.generation or not isinstance(instance, str) or
                not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", instance) or
                error not in ("", "apply_failed", "managed_policy_missing", "outdated_companion")):
            return {"ok": False, "error": "bad_ack"}
        self.clients[(uid, instance)] = (time.monotonic(), generation, error)
        self.clients = {key: value for key, value in self.clients.items() if time.monotonic() - value[0] < 30}
        if len(self.clients) > 128:
            oldest = min(self.clients, key=lambda key: self.clients[key][0])
            del self.clients[oldest]
        return {"ok": True}

    def status(self, uid):
        profile = self.school.policy_for(uid)
        enabled = bool(profile and profile.profile["websites_enabled"])
        clients = [value for (user, _), value in self.clients.items()
                   if user == uid and time.monotonic() - value[0] < 15 and value[1] == self.generation]
        received = bool(clients) and all(not value[2] for value in clients)
        error = self.error or next((value[2] for value in clients if value[2]), "")
        return {"enabled": enabled, "ready": self.ready(), "activeDomains": len(self.domains),
                "browserReceived": received, "error": error, "otherAccounts": bool(self.domains) and
                (not enabled or self.school.snapshot(uid, self.school.host.clock.now()).get("mode") != "school")}

    def close(self):
        if self.asset_server:
            self.asset_server.close()
