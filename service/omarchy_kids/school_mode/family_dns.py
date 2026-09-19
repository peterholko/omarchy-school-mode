"""Reversible laptop-wide Cloudflare Families DNS, independent of school hours.

Keep DHCP/connection profiles intact. NetworkManager's global DNS is used for
resolv.conf clients; resolved gets the same servers for nss-resolve/stub clients.
NetworkManager must not also give resolved unfiltered per-link DHCP servers.
"""
import configparser
import fcntl
import hashlib
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
# Without a DNS-over-TLS line the administrator's own setting applies. Service
# 4.4.0-4.4.2 wrote exactly this text, so their enabled files remain recognized.
RESOLVED_INHERIT = ("# Managed by School / Free Time. Applies to every account and both modes.\n"
                    "[Resolve]\nDNS=\nDNS=" + " ".join(ip + "#family.cloudflare-dns.com" for ip in SERVERS) +
                    "\nFallbackDNS=\nDomains=\nDomains=~.\n")
# Routers readily redirect port 53. Like Omarchy's own Cloudflare choice, try
# TLS first and keep resolving on networks where port 853 is closed.
RESOLVED_ON = RESOLVED_INHERIT + "DNSOverTLS=opportunistic\n"
POLICY_NAME = "91-omarchy-school-family-dns.json"
POLICY_ON = '{"DnsOverHttpsMode":"off"}\n'
POLICY_OFF = "{}\n"
RESOLV_LINKS = {"/run/NetworkManager/resolv.conf", "/run/systemd/resolve/stub-resolv.conf",
                "/run/systemd/resolve/resolv.conf", "/usr/lib/systemd/resolv.conf", "/lib/systemd/resolv.conf"}
# Written by Omarchy's own DNS menu (omarchy-dns) for Cloudflare, Google and Custom.
OMARCHY_DNS = "NetworkManager/conf.d/20-omarchy-dns.conf"
RETRY, RETRY_LIMIT = 30, 3600


class Disrupted(ValueError):
    """The change failed after DNS was reloaded, so repeating it is not free."""


def files(etc):
    """Owned path -> (off text, on text, other texts this installer writes there)."""
    return {etc / "NetworkManager/conf.d" / NAME: (OFF, NM_ON, ()),
            etc / "systemd/resolved.conf.d" / NAME: (OFF, RESOLVED_ON, (RESOLVED_INHERIT,)),
            **{etc / browser / "policies/managed" / POLICY_NAME: (POLICY_OFF, POLICY_ON, ())
               for browser in ("chromium", "opt/chrome")}}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def recorded(value, etc):
    """Receipt files as path -> SHA-256 digests of the texts we last wrote.

    Digests let a later release change its texts or its set of files without
    mistaking ours for an administrator's. Service 4.4.0-4.4.2 listed paths
    only; their files are matched against the texts those releases wrote.
    """
    if isinstance(value, list) and all(isinstance(path, str) for path in value):
        value = {path: [] for path in value}
    if not isinstance(value, dict) or any(
            not isinstance(path, str) or etc not in Path(path).parents or ".." in Path(path).parts
            or Path(path).name not in (NAME, POLICY_NAME)
            or not isinstance(digests, list) or any(not isinstance(item, str) for item in digests)
            for path, digests in value.items()):
        raise ValueError("Unknown Family DNS installation receipt.")
    return value


def command(*args):
    try:
        return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=6,
                              env={**os.environ, "LC_ALL": "C", "SYSTEMD_COLORS": "0"}).stdout
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"Family DNS timed out running {' '.join(args)}. Check the network services and retry.") from error
    except subprocess.CalledProcessError as error:
        detail = " ".join((error.stderr or error.stdout or "No error details returned.").split())[:600]
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
        header = re.fullmatch(r"(Global|Link (\d+) \(([^\r\n]*)\)|Delegate [^:\r\n]+):\s*(.*)", line)
        if header:
            section = {"label": header[1], "index": header[2], "name": header[3], "servers": set()}
            sections.append(section)
            values = header[4]
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
            if not isinstance(previous, dict) or previous.get("identity") != IDENTITY:
                raise ValueError("Unknown Family DNS installation receipt.")
            previous["files"] = recorded(previous.get("files"), self.etc)
        current = files(self.etc)
        ours = previous.get("files", {})
        # Paths an earlier release owned are checked too, before setup releases them.
        for path in [*current, *(Path(name) for name in ours if Path(name) not in current)]:
            for parent in path.parents:
                if parent == self.etc.parent:
                    break
                if parent.exists() or parent.is_symlink():
                    owned(parent)
            if path.exists() or path.is_symlink():
                owned(path)
                if str(path) not in ours:
                    raise ValueError(f"Family DNS installation collision at {path}")
                text = path.read_text()
                off, on, others = current.get(path, ("", "", ()))
                if digest(text) not in ours[str(path)] and (path not in current or text not in (off, on, *others)):
                    raise ValueError(f"Family DNS file was edited: {path}")
        return previous

    def install(self):
        receipt = self.plan() or {"identity": IDENTITY, "files": {}, "pending": False}
        current = files(self.etc)
        # Release a file only an earlier release used before forgetting it, so
        # an interrupted setup cannot leave an unrecorded policy behind.
        for name in [name for name in receipt["files"] if Path(name) not in current]:
            Path(name).unlink(missing_ok=True)
            del receipt["files"][name]
        for path, values in current.items():
            accepted = receipt["files"].setdefault(str(path), [])
            present = digest(path.read_text() if path.exists() else values[0])
            if present not in accepted:
                accepted.append(present)
        # Ownership is recorded before creating files so an interrupted setup is retryable.
        write_private(self.receipt, json.dumps(receipt) + "\n")
        for path, values in current.items():
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir(mode=0o755)
                parent.chmod(0o755)
            if not path.exists():
                write_public(path, values[0])

    def ready(self):
        try:
            return bool(self.plan()) and all(path.is_file() for path in files(self.etc))
        except (OSError, ValueError):
            return False

    def nm_config(self):
        result = configparser.ConfigParser(interpolation=None, strict=False)
        result.read_string(self.run("/usr/bin/NetworkManager", "--print-config"))
        return result

    def nm_managed(self, name):
        return self.run("/usr/bin/nmcli", "--get-values", "GENERAL.NM-MANAGED", "device", "show", name).strip() == "yes"

    def strict_tls(self):
        """Whether an administrator requires DNS-over-TLS, which is never relaxed."""
        value = ""
        directory = self.etc / "systemd/resolved.conf.d"
        for path in [self.etc / "systemd/resolved.conf", *sorted(directory.glob("*.conf"))]:
            if path.name == NAME or not path.is_file():
                continue
            for line in path.read_text(errors="replace").splitlines():
                key, separator, setting = line.partition("=")
                if separator and key.strip() == "DNSOverTLS":
                    value = setting.strip().lower()
        return value in ("1", "yes", "y", "true", "t", "on")

    def contents(self, enabled):
        result = {path: values[int(enabled)] for path, values in files(self.etc).items()}
        if enabled and self.strict_tls():
            result[self.etc / "systemd/resolved.conf.d" / NAME] = RESOLVED_INHERIT
        return result

    def preflight(self):
        """Report every conflict that is visible before DNS is touched."""
        try:
            states = self.run("/usr/bin/systemctl", "is-active", "NetworkManager.service", "systemd-resolved.service").split()
        except ValueError:
            states = []  # systemctl exits non-zero, without details, when neither is active.
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
            if (self.etc / OMARCHY_DNS).exists():
                raise ValueError("Omarchy's DNS setting is Cloudflare, Google or Custom. Choose DHCP under Setup > Network > DNS, "
                                 "or run omarchy dns DHCP, then turn Family DNS on again.")
            raise ValueError("NetworkManager already has global DNS settings. Review those before enabling Family DNS.")
        for path in files(self.etc):
            if path.suffix != ".json":
                continue
            for directory in (path.parent, path.parent.with_name("recommended")):
                for other in directory.glob("*.json"):
                    if other == path:
                        continue
                    try:
                        policy = json.loads(other.read_text())
                    except (OSError, ValueError) as error:
                        raise ValueError(f"Cannot inspect the browser policy {other}. Review it before enabling Family DNS.") from error
                    if not isinstance(policy, dict) or {"DnsOverHttpsMode", "DnsOverHttpsTemplates"}.intersection(policy):
                        raise ValueError(f"Browser DNS policy conflict in {other}. Review it before enabling Family DNS.")
        # Only NetworkManager's links are cleared later. Another tool's resolver
        # would fail verification after a reload that then has to be undone. The
        # global list is replaced by our drop-in, so verify() judges that result.
        for section in resolved_configuration(self.run("/usr/bin/resolvectl", "dns")):
            extra = sorted(section["servers"] - set(SERVERS))
            if not extra or section["label"] == "Global" or (section["index"] and self.nm_managed(section["name"])):
                continue
            raise ValueError(f"{section['name'] or section['label']} uses its own DNS ({', '.join(extra)}), set outside NetworkManager. "
                             "Family DNS does not clear it. Disconnect that VPN or interface, or remove those servers, then retry.")

    def reload(self, enabled):
        # Do not restart NetworkManager or bring Wi-Fi connections down.
        if enabled:
            self.run("/usr/bin/nmcli", "general", "reload", "conf")
            self.run("/usr/bin/systemctl", "restart", "systemd-resolved.service")
            # resolved persists D-Bus per-link settings across restarts. Stop
            # NM's updates first, then clear only its managed links' DNS lists.
            # Unlike `revert`, this leaves mDNS/LLMNR and routing settings alone.
            for link in resolved_configuration(self.run("/usr/bin/resolvectl", "dns")):
                if link["index"] and link["servers"] and self.nm_managed(link["name"]):
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

    def healthy(self):
        try:
            self.verify()
        except (OSError, ValueError, configparser.Error):
            return False
        return True

    def apply(self, enabled):
        if not self.receipt.exists() and not enabled:
            return
        # Also serializes against command-line removal and a replacement daemon.
        with (self.config / ".school-family-dns.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._apply(enabled)

    def settle(self, receipt, texts):
        receipt["pending"] = False
        receipt["files"].update({str(path): [digest(text)] for path, text in texts.items()})
        write_private(self.receipt, json.dumps(receipt) + "\n")

    def _apply(self, enabled):
        receipt = self.plan()
        current = files(self.etc)
        if not receipt or not all(p.is_file() for p in current):
            raise ValueError("Run the updated School Mode setup before enabling Family DNS.")
        before = {p: p.read_text() for p in current}
        if not enabled and not receipt.get("pending") and all(before[p] == values[0] for p, values in current.items()):
            return
        if enabled:
            self.preflight()
        desired = self.contents(enabled)
        # A reboot or service restart finds working Family DNS as it left it:
        # check it without restarting the resolver under the running desktop.
        if enabled and not receipt.get("pending") and before == desired and self.healthy():
            return
        # Every text this installer enables with, past or future, sets global DNS.
        was_enabled = "[global-dns-domain-*]" in before[self.etc / "NetworkManager/conf.d" / NAME]
        receipt["pending"] = True
        # Until this settles either text may be on disk, and both are ours.
        receipt["files"].update({str(p): sorted({digest(before[p]), digest(desired[p])}) for p in current})
        write_private(self.receipt, json.dumps(receipt) + "\n")
        try:
            for path, text in desired.items():
                write_public(path, text)
            self.reload(enabled)
            if enabled:
                self.verify()
        except Exception as error:
            # Restore exactly our prior files. Never erase another tool's settings.
            detail = str(error) if isinstance(error, (OSError, ValueError, configparser.Error)) else f"{type(error).__name__}: {error}"
            try:
                for path, text in before.items():
                    write_public(path, text)
                self.reload(was_enabled)
            except Exception as rollback:
                raise Disrupted(f"{detail} DNS restoration also failed; turn the toggle off and retry setup. {rollback}") from error
            self.settle(receipt, before)
            raise Disrupted(detail) from error
        self.settle(receipt, desired)

    def remove(self):
        if not self.plan():
            return
        with (self.config / ".school-family-dns.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._apply(False)
            for path in {*files(self.etc), *map(Path, self.plan()["files"])}:
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
        self.failures = 0
        self.monotonic = time.monotonic

    def reconcile(self):
        desired = self.school.config["family_dns_enabled"] and bool(self.school.config["users"])
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            if desired == self.target and (not self.error or self.monotonic() < self.retry_at):
                return
            # A parent's new choice is tried at once, whatever the retry time.
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
                self.active, self.failures = desired, 0
        except Exception as error:
            expected = isinstance(error, (OSError, ValueError, configparser.Error))
            message = str(error) if expected else f"Family DNS stopped unexpectedly ({type(error).__name__}: {error})."
            if not expected:
                self.school.host.log(f"family dns: {message}")
            with self.lock:
                # A conflict found before any change is cheap to look for again.
                # One found after a reload restarted the resolver twice, so those
                # attempts are spaced out instead of repeated twice a minute.
                self.failures = min(self.failures + 1, 8) if isinstance(error, Disrupted) or not expected else 0
                delay = min(RETRY * 2 ** max(self.failures - 1, 0), RETRY_LIMIT)
                if delay > RETRY:
                    message += f" Trying again in {delay // 60} min; switch the toggle off and on to retry sooner."
                self.active = False
                self.error = message
                self.retry_at = self.monotonic() + delay

    def status(self):
        with self.lock:
            desired = self.school.config["family_dns_enabled"] and bool(self.school.config["users"])
            return {"enabled": self.school.config["family_dns_enabled"], "active": self.active,
                    "applying": desired != self.target or bool(self.worker and self.worker.is_alive()),
                    "ready": self.integration.ready(), "error": self.error}
