"""Reversible laptop-wide Cloudflare Families DNS, independent of school hours.

Keep DHCP/connection profiles intact. NetworkManager's global DNS is used for
resolv.conf clients; resolved gets the same servers for nss-resolve/stub clients.
NetworkManager must not also give resolved unfiltered per-link DHCP servers.
"""
import configparser
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from omarchy_kids.core.paths import write_private, write_public
from .websites_setup import owned

IDENTITY = "io.github.peterholko.school-mode.family-dns"
CONFIG = Path("/etc/omarchy-kids-controls")
ETC = Path("/etc")
SERVERS = ("1.1.1.3", "1.0.0.3", "2606:4700:4700::1113", "2606:4700:4700::1003")
NAME = "99-omarchy-school-family-dns.conf"
OFF = "# Managed by School / Free Time. Cloudflare Family DNS is off.\n"
# NetworkManager.conf lists use commas; .nmconnection files use semicolons.
NM_ON = ("# Managed by School / Free Time. Applies to every account and both modes.\n"
         "[main]\ndns=default\nrc-manager=symlink\nsystemd-resolved=false\n"
         "[global-dns]\nsearches=\noptions=\n[global-dns-domain-*]\nservers=" + ",".join(SERVERS) + "\n")
RESOLVED_ON = ("# Managed by School / Free Time. Applies to every account and both modes.\n"
               "[Resolve]\nDNS=\nDNS=" + " ".join(ip + "#family.cloudflare-dns.com" for ip in SERVERS) +
               "\nFallbackDNS=\nDomains=\nDomains=~.\n")
POLICY_NAME = "91-omarchy-school-family-dns.json"
POLICY_ON = '{"DnsOverHttpsMode":"off"}\n'
POLICY_OFF = "{}\n"
RESOLV_LINKS = {"/run/NetworkManager/resolv.conf", "/run/systemd/resolve/stub-resolv.conf",
                "/run/systemd/resolve/resolv.conf", "/usr/lib/systemd/resolv.conf", "/lib/systemd/resolv.conf"}


def files(etc):
    return {etc / "NetworkManager/conf.d" / NAME: (OFF, NM_ON),
            etc / "systemd/resolved.conf.d" / NAME: (OFF, RESOLVED_ON),
            **{etc / browser / "policies/managed" / POLICY_NAME: (POLICY_OFF, POLICY_ON)
               for browser in ("chromium", "opt/chrome")}}


def command(*args):
    try:
        return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=6,
                              env={**os.environ, "LC_ALL": "C", "SYSTEMD_COLORS": "0"}).stdout
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"Family DNS timed out running {' '.join(args)}. Check the network services and retry.") from error
    except subprocess.CalledProcessError as error:
        detail = " ".join((error.stderr or "No error details returned.").split())[:600]
        raise ValueError(f"Family DNS command failed ({' '.join(args)}): {detail}") from error
    except OSError as error:
        raise ValueError(f"Could not run {' '.join(args)} for Family DNS: {error}") from error


def resolved_configuration(output):
    """Read resolvectl's labelled blocks, including wrapped continuation lines.

    It wraps even with stdout piped. A colon on an indented IPv6 line is part
    of the address, not a separator between the label and its server list.
    """
    sections = []
    section = None
    for line in output.splitlines():
        if not line.strip():
            continue
        header = re.fullmatch(r"(?:Global|Link (\d+) \(([^\r\n]*)\)|Delegate [^:\r\n]+):\s*(.*)", line)
        if header:
            section = {"index": header[1], "name": header[2], "servers": set()}
            sections.append(section)
            values = header[3]
        elif section is not None and line[:1].isspace():
            values = line.strip()
        else:
            raise ValueError("Could not read systemd-resolved's DNS output. Run resolvectl dns to inspect it.")
        for value in values.split():
            try:
                section["servers"].add(str(ipaddress.ip_address(value.split("#", 1)[0].split("%", 1)[0])))
            except ValueError as error:
                raise ValueError(f"Could not read a systemd-resolved DNS address: {value[:120]}") from error
    if not sections:
        raise ValueError("systemd-resolved did not return its DNS configuration. Retry the toggle.")
    return sections


class Integration:
    def __init__(self, config=CONFIG, etc=ETC, run=command):
        self.config, self.etc, self.run = Path(config), Path(etc), run
        self.receipt = self.config / "school-family-dns.json"

    def plan(self):
        previous = {}
        if self.receipt.exists() or self.receipt.is_symlink():
            owned(self.receipt)
            previous = json.loads(self.receipt.read_text())
            if (not isinstance(previous, dict) or previous.get("identity") != IDENTITY or
                    previous.get("files") != [str(p) for p in files(self.etc)]):
                raise ValueError("Unknown Family DNS installation receipt.")
        for path, contents in files(self.etc).items():
            for parent in path.parents:
                if parent == self.etc.parent:
                    break
                if parent.exists() or parent.is_symlink():
                    owned(parent)
            if path.exists() or path.is_symlink():
                owned(path)
                if not previous:
                    raise ValueError(f"Family DNS installation collision at {path}")
                if path.read_text() not in contents:
                    raise ValueError(f"Family DNS file was edited: {path}")
        return previous

    def install(self):
        previous = self.plan()
        write_private(self.receipt, json.dumps(previous or {
            "identity": IDENTITY, "files": [str(p) for p in files(self.etc)], "pending": False}) + "\n")
        for path, contents in files(self.etc).items():
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir(mode=0o755)
                parent.chmod(0o755)
            if not path.exists():
                write_public(path, contents[0])

    def ready(self):
        try:
            return bool(self.plan()) and all(path.is_file() for path in files(self.etc))
        except (OSError, ValueError):
            return False

    def nm_config(self):
        result = configparser.ConfigParser(interpolation=None, strict=False)
        result.read_string(self.run("/usr/bin/NetworkManager", "--print-config"))
        return result

    def preflight(self):
        states = self.run("/usr/bin/systemctl", "is-active", "NetworkManager.service", "systemd-resolved.service").split()
        if states != ["active", "active"]:
            raise ValueError("Family DNS needs NetworkManager and systemd-resolved running.")
        resolv = self.etc / "resolv.conf"
        if resolv.is_symlink():
            target = os.path.normpath(os.path.join("/etc", os.readlink(resolv)))
            if target not in RESOLV_LINKS:
                raise ValueError("Another DNS manager controls resolv.conf. Restore Omarchy's network setup before enabling Family DNS.")
        else:
            owned(resolv)
        effective = self.nm_config()
        if effective.get("main", "dns", fallback="default") not in ("default", "systemd-resolved"):
            raise ValueError("Another DNS manager is configured in NetworkManager. Review it before enabling Family DNS.")
        if effective.get("main", "rc-manager", fallback="auto") not in ("auto", "symlink", "file"):
            raise ValueError("NetworkManager is not managing resolv.conf. Restore Omarchy's DNS setup before enabling Family DNS.")
        # Existing global/split DNS policies are never silently adopted.
        nm_path = self.etc / "NetworkManager/conf.d" / NAME
        if nm_path.read_text() == OFF and any(s.startswith("global-dns") for s in effective.sections()):
            raise ValueError("NetworkManager already has global DNS settings. Review those before enabling Family DNS.")
        for path in files(self.etc):
            if path.suffix != ".json":
                continue
            for directory in (path.parent, path.parent.with_name("recommended")):
                for other in directory.glob("*.json"):
                    if other == path:
                        continue
                    policy = json.loads(other.read_text())
                    if not isinstance(policy, dict) or {"DnsOverHttpsMode", "DnsOverHttpsTemplates"}.intersection(policy):
                        raise ValueError(f"Browser DNS policy conflict in {other}. Review it before enabling Family DNS.")

    def reload(self, enabled):
        # Do not restart NetworkManager or bring Wi-Fi connections down.
        if enabled:
            self.run("/usr/bin/nmcli", "general", "reload", "conf")
            self.run("/usr/bin/systemctl", "restart", "systemd-resolved.service")
            # resolved persists D-Bus per-link settings across restarts. Stop
            # NM's updates first, then clear only its managed links' DNS lists.
            # Unlike `revert`, this leaves mDNS/LLMNR and routing settings alone.
            for link in resolved_configuration(self.run("/usr/bin/resolvectl", "dns")):
                if not link["index"] or not link["servers"]:
                    continue
                managed = self.run("/usr/bin/nmcli", "--get-values", "GENERAL.NM-MANAGED",
                                   "device", "show", link["name"]).strip()
                if managed == "yes":
                    self.run("/usr/bin/resolvectl", "dns", link["index"], "")
        else:
            self.run("/usr/bin/systemctl", "restart", "systemd-resolved.service")
            # These are distinct reloads: nmcli rejects two flag arguments.
            self.run("/usr/bin/nmcli", "general", "reload", "conf")
            self.run("/usr/bin/nmcli", "general", "reload", "dns-full")

    def verify(self):
        effective = self.nm_config()
        if (effective.get("main", "dns", fallback="") != "default" or
                effective.get("main", "systemd-resolved", fallback="") != "false" or
                effective.get("main", "rc-manager", fallback="") != "symlink" or
                {s for s in effective.sections() if s.startswith("global-dns-domain-")} != {"global-dns-domain-*"} or
                {ip.strip() for ip in effective.get("global-dns-domain-*", "servers", fallback="").split(",")} != set(SERVERS)):
            raise ValueError("Another NetworkManager configuration overrides Family DNS. Review it before retrying.")
        servers = {server for section in resolved_configuration(self.run("/usr/bin/resolvectl", "dns"))
                   for server in section["servers"]}
        if servers != set(SERVERS):
            unexpected = sorted(servers - set(SERVERS))
            missing = sorted(set(SERVERS) - servers)
            details = []
            if unexpected:
                details.append("additional servers: " + ", ".join(unexpected))
            if missing:
                details.append("missing Family DNS servers: " + ", ".join(missing))
            raise ValueError("systemd-resolved DNS does not match Family DNS (" + "; ".join(details) + "). Check resolvectl dns and resolver settings.")
        nameservers = [line.split()[1] for line in (self.etc / "resolv.conf").read_text().splitlines()
                       if line.split()[:1] == ["nameserver"] and len(line.split()) >= 2]
        allowed = {*SERVERS, "127.0.0.53", "127.0.0.54"}
        if not nameservers or any(str(ipaddress.ip_address(ip)) not in allowed for ip in nameservers):
            raise ValueError("resolv.conf did not accept Family DNS. Check its DNS manager and permissions before retrying.")

    def apply(self, enabled):
        if not self.receipt.exists() and not enabled:
            return
        # Also serializes against command-line removal and a replacement daemon.
        with (self.config / ".school-family-dns.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._apply(enabled)

    def _apply(self, enabled):
        receipt = self.plan()
        if not receipt or not all(p.is_file() for p in files(self.etc)):
            raise ValueError("Run the updated School Mode setup before enabling Family DNS.")
        before = {p: p.read_text() for p in files(self.etc)}
        if not enabled and not receipt.get("pending") and all(before[p] == values[0] for p, values in files(self.etc).items()):
            return
        if enabled:
            self.preflight()
        was_enabled = before[self.etc / "NetworkManager/conf.d" / NAME] == NM_ON
        receipt["pending"] = True
        write_private(self.receipt, json.dumps(receipt) + "\n")
        try:
            for path, values in files(self.etc).items():
                write_public(path, values[int(enabled)])
            self.reload(enabled)
            if enabled:
                self.verify()
        except (OSError, ValueError, configparser.Error) as error:
            # Restore exactly our prior files. Never erase another tool's settings.
            try:
                for path, text in before.items():
                    write_public(path, text)
                self.reload(was_enabled)
            except (OSError, ValueError) as rollback:
                raise ValueError(f"{error} DNS restoration also failed; turn the toggle off and retry setup. {rollback}") from error
            receipt["pending"] = False
            write_private(self.receipt, json.dumps(receipt) + "\n")
            raise
        receipt["pending"] = False
        write_private(self.receipt, json.dumps(receipt) + "\n")

    def remove(self):
        if not self.plan():
            return
        with (self.config / ".school-family-dns.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._apply(False)
            for path in files(self.etc):
                path.unlink(missing_ok=True)
            self.receipt.unlink()


class FamilyDNS:
    """Apply network changes away from the timer/launcher service thread."""
    def __init__(self, school):
        self.school = school
        layout = school.host.layout
        etc = ETC if layout.mode == "system" else layout.config_path.parent / "dns-etc"
        self.integration = Integration(layout.config_path.parent, etc)
        self.lock = threading.Lock()
        self.worker = None
        self.target = None
        self.active = False
        self.error = ""
        self.retry_at = 0

    def reconcile(self):
        desired = self.school.config["family_dns_enabled"] and bool(self.school.config["users"])
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            if desired == self.target and (not self.error or time.monotonic() < self.retry_at):
                return
            self.target = desired
            if not desired and not self.integration.receipt.exists():
                self.active, self.error = False, ""
                return
            self.error = ""
            self.worker = threading.Thread(target=self._apply, args=(desired,), daemon=True)
            self.worker.start()

    def _apply(self, desired):
        try:
            self.integration.apply(desired)
            with self.lock:
                self.active = desired
        except (OSError, ValueError, configparser.Error) as error:
            with self.lock:
                self.active = False
                self.error = str(error)
                self.retry_at = time.monotonic() + 30

    def status(self):
        with self.lock:
            desired = self.school.config["family_dns_enabled"] and bool(self.school.config["users"])
            return {"enabled": self.school.config["family_dns_enabled"], "active": self.active,
                    "applying": desired != self.target or bool(self.worker and self.worker.is_alive()),
                    "ready": self.integration.ready(), "error": self.error}
