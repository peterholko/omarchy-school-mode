"""One local transport and clock hosting independently installed parent modules."""
import importlib.util
import json
import os
import pwd
import signal
import socket
import threading
from omarchy_kids import API_VERSION, VERSION
from . import clock, paths, proto
from .auth import ParentAuth
from .migrate import migrate
from .storage import read_json, write_json


class Daemon:
    def __init__(self, layout, tick_seconds=5, log=print, modules=None):
        self.layout = layout
        self.tick_seconds = tick_seconds
        self.log = log
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.clock_path = layout.config_path.with_name(".parent-clock.json")
        self.clock = clock.Clock(read_json(self.clock_path, {}).get("last_logical"))
        self.auth = ParentAuth()
        self.server = None
        self.connections = threading.BoundedSemaphore(32)
        self.services = {}
        self.health = {}
        migrate(layout)
        allowed = {"school": "school_mode", "time": "screen_time"}
        for name, package in allowed.items():
            if modules is not None and name not in modules:
                continue
            if importlib.util.find_spec("omarchy_kids." + package) is None:
                continue
            module = __import__("omarchy_kids." + package + ".service", fromlist=["Service"])
            self.services[name] = module.Service(self)
            self.health[name] = {"healthy": True}

    @staticmethod
    def resolve_uid(peer, message):
        if peer != 0:
            return peer
        try:
            return pwd.getpwnam(str(message.get("user", ""))).pw_uid
        except KeyError:
            return peer

    def school_snapshot(self, uid, now):
        school = self.services.get("school")
        return school.snapshot(uid, now) if school else {}

    def refresh(self, now):
        # Policy first, then the budget gate: a mode change updates both before
        # its success reply. No wall-clock time is charged by this refresh.
        for service in self.services.values():
            service.tick(now, 0)

    def dispatch(self, peer, message):
        command = str(message.get("cmd", ""))
        if command == "ping":
            with self.lock:
                return {"ok": True, "mode": self.layout.mode, "version": VERSION, "apiVersion": API_VERSION,
                        "modules": {name: {"installed": True, "users": len(service.managed_uids()), **self.health[name]}
                                    for name, service in self.services.items()}}
        scope = message.get("scope", "time")
        if command in ("mode.get", "mode.set"):
            scope = "school"
        # Old clients can still send a school-only patch to the time socket.
        # A mixed patch is rejected intact instead of partially saving it.
        if command == "config.patch" and scope == "time":
            patch = message.get("patch", {})
            if isinstance(patch, dict):
                periods = patch.get("blocked_periods", [])
                has_school = "school_apps" in patch or (isinstance(periods, list) and any(isinstance(p, dict) and p.get("mode") == "free" for p in periods))
                if has_school:
                    has_time = bool(set(patch) - {"school_apps", "blocked_periods"}) or (isinstance(periods, list) and any(isinstance(p, dict) and p.get("mode", "block") != "free" for p in periods))
                    if has_time:
                        return {"ok": False, "error": "mixed_module_patch", "detail": "Save school and screen-time settings separately."}
                    scope = "school"
        if command == "config.set" and scope == "time":
            incoming = message.get("config")
            if not isinstance(incoming, dict) or not isinstance(incoming.get("profiles", {}), dict):
                return {"ok": False, "error": "bad_config"}
            profiles = incoming.get("profiles", {})
            for profile in profiles.values():
                if not isinstance(profile, dict):
                    return {"ok": False, "error": "bad_config"}
                periods = profile.get("blocked_periods", [])
                if not isinstance(periods, list):
                    return {"ok": False, "error": "bad_config"}
                if "school_apps" in profile or any(isinstance(p, dict) and p.get("mode") == "free" for p in periods):
                    return {"ok": False, "error": "mixed_module_patch"}
        service = self.services.get(scope) if isinstance(scope, str) else None
        if service is None:
            return {"ok": False, "error": "module_not_installed", "module": scope}
        result = service.dispatch(peer, message)
        result.setdefault("apiVersion", API_VERSION)
        return result

    def listen(self):
        self.layout.runtime_dir.mkdir(parents=True, exist_ok=True)
        if self.layout.mode == "system":
            os.chmod(self.layout.runtime_dir, 0o755)
        else:
            paths.private_dir(self.layout.runtime_dir, scrub=False)
        path = self.layout.socket_path
        path.unlink(missing_ok=True)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        os.chmod(path, 0o666 if self.layout.mode == "system" else 0o600)
        self.server.listen(16)
        self.server.settimeout(1)

    def handle(self, connection):
        try:
            connection.settimeout(30)
            uid = proto.peer_uid(connection)
            reader = proto.LineReader(connection)
            while True:
                message = reader.read()
                if message is None:
                    break
                if not isinstance(message, dict):
                    proto.write_line(connection, {"ok": False, "error": "bad_request"})
                    continue
                if message.get("cmd") == "watch":
                    self.stream(connection, uid, message.get("scope", "time"))
                    break
                proto.write_line(connection, self.dispatch(uid, message))
        except (OSError, proto.ProtocolError):
            pass
        except Exception as exc:
            self.log(f"client request failed: {type(exc).__name__}")
            try:
                proto.write_line(connection, {"ok": False, "error": "internal"})
            except OSError:
                pass
        finally:
            connection.close()

    def stream(self, connection, uid, scope):
        previous = None
        while not self.stop_event.is_set():
            payload = self.dispatch(uid, {"cmd": "status", "scope": scope})
            if payload != previous:
                proto.write_line(connection, payload)
                previous = payload
            self.stop_event.wait(1)

    def limited_handle(self, connection):
        try:
            self.handle(connection)
        finally:
            self.connections.release()

    def serve(self):
        while not self.stop_event.is_set():
            try:
                conn, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.connections.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self.limited_handle, args=(conn,), daemon=True).start()

    def run(self):
        self.listen()
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        threading.Thread(target=self.serve, daemon=True).start()
        try:
            while not self.stop_event.is_set():
                now, elapsed = self.clock.tick()
                write_json(self.clock_path, {"last_logical": now})
                with self.lock:
                    for name, service in self.services.items():
                        try:
                            service.tick(now, elapsed)
                            self.health[name] = {"healthy": True}
                        except Exception as exc:
                            self.health[name] = {"healthy": False, "error": type(exc).__name__}
                            self.log(f"{name} update failed: {exc}")
                self.stop_event.wait(self.tick_seconds)
        finally:
            with self.lock:
                write_json(self.clock_path, {"last_logical": self.clock.now()})
                for service in self.services.values():
                    service.save()
            self.layout.socket_path.unlink(missing_ok=True)

    def shutdown(self, *_):
        self.stop_event.set()
        if self.server is not None:
            self.server.close()


def main():
    Daemon(paths.detect(), tick_seconds=float(os.environ.get("SCREEN_TIME_TICK_SECONDS", "5"))).run()
