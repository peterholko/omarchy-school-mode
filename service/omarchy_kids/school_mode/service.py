"""School policy service; no import or requirement for the time module."""
import copy
import os
import pwd
from . import config, pam_setup
from .policy import Policy
from .domains import normalize_domains, MAX_DOMAINS
from .websites import Websites
from omarchy_kids.core import session
from omarchy_kids.core.storage import read_json, write_json, school_config_path, public_status


class Service:
    def __init__(self, host):
        self.host = host
        self.path = school_config_path(host.layout)
        self.config = config.sanitize(read_json(self.path, {}))
        self.policies = {}
        self.sessions = {}
        self.last_lock = {}
        self.websites = Websites(self)

    def managed_uids(self):
        result = []
        for user in self.config["users"]:
            try:
                result.append(pwd.getpwnam(user).pw_uid)
            except KeyError:
                self.host.log(f"school mode: unknown account {user}")
        return result

    def policy_for(self, uid):
        if uid not in self.managed_uids():
            return None
        name = session.username_for(uid)
        key = self.config["users"][name]["profile"]
        if uid not in self.policies:
            policy = Policy(self.config["profiles"][key])
            policy.restore_override(read_json(self.override_path(uid), {}), self.host.clock.now())
            self.policies[uid] = policy
        self.policies[uid].profile = self.config["profiles"][key]
        return self.policies[uid]

    def override_path(self, uid):
        return self.host.layout.state_dir.parent / "school-mode" / str(uid) / "override.json"

    def snapshot(self, uid, now):
        policy = self.policy_for(uid)
        if policy is None:
            return {}
        before = policy.export_override()
        result = policy.snapshot(now)
        if policy.export_override() != before:
            write_json(self.override_path(uid), policy.export_override())
        return result

    def status(self, uid, now):
        policy = self.policy_for(uid)
        if policy is None:
            return {"ok": False, "error": "not_managed", "enabled": False, "schemaVersion": 1}
        return {"ok": True, "enabled": True, "schemaVersion": 1,
                **self.snapshot(uid, now), "blocked_periods": policy.profile["blocked_periods"],
                "free_time_timer_version": 1, "free_time_ready": pam_setup.ready(),
                "websites": self.websites.status(uid)}

    def publish(self, uid, now):
        data = self.status(uid, now)
        public = {"schemaVersion": 1, "enabled": data.get("enabled", False), "updatedAt": now,
                  "revision": data.get("revision", 0), "mode": data.get("mode", "free"),
                  "modeReason": data.get("mode_reason", ""), "schoolApps": data.get("school_apps", []),
                  "schoolUntil": data.get("school_until", ""), "schoolLabel": data.get("school_label", ""),
                  "blockedPeriods": data.get("blocked_periods", []),
                  "freeTimeTimerVersion": 1, "freeTimeReady": data.get("free_time_ready", False),
                  "freeTimeMinutes": data.get("free_time_minutes", 30),
                  "freeTimeRemainingSeconds": data.get("free_time_remaining_seconds", 0),
                  "freeTimeExpired": data.get("free_time_expired", False),
                  "websites": data.get("websites", {})}
        public_status(self.host.layout, session.username_for(uid), "school-mode", public)

    def dispatch(self, peer, message):
        uid = self.host.resolve_uid(peer, message)
        command = message.get("cmd")
        if command in ("websites.status", "websites.ack"):
            with self.host.lock:
                self.websites.reconcile(self.host.clock.now())
                if command == "websites.ack":
                    return self.websites.acknowledge(peer, message)
                return self.websites.wire_status()
        if command == "users":
            if peer != 0:
                return {"ok": False, "error": "not_allowed"}
            return {"ok": True, "users": sorted(self.config["users"])}
        if command == "users.set":
            if peer != 0:
                return {"ok": False, "error": "not_allowed"}
            name = message.get("user")
            try:
                target = pwd.getpwnam(name).pw_uid
            except (KeyError, TypeError):
                return {"ok": False, "error": "unknown_user"}
            if target == 0:
                return {"ok": False, "error": "not_allowed"}
            with self.host.lock:
                if message.get("enabled", True):
                    if name not in self.config["users"]:
                        profiles = self.config["profiles"]
                        key = self.config["disabled_users"].pop(name, {"profile": name})["profile"]
                        if key not in profiles:
                            profiles[key] = copy.deepcopy(profiles[self.config["active_profile"]])
                            profiles[key]["name"] = name
                        self.config["users"][name] = {"profile": key}
                else:
                    previous = self.config["users"].pop(name, None)
                    if previous is not None:
                        self.config["disabled_users"][name] = previous
                    self.policies.pop(target, None)
                    self.override_path(target).unlink(missing_ok=True)
                write_json(self.path, self.config)
                self.websites.reconcile(self.host.clock.now())
                self.publish(target, self.host.clock.now())
            return {"ok": True, "users": sorted(self.config["users"])}
        with self.host.lock:
            policy = self.policy_for(uid)
            if policy is None:
                return {"ok": False, "error": "not_managed"}
            if command in ("mode.get", "status"):
                return self.status(uid, self.host.clock.now())
        if command == "mode.set":
            mode = message.get("mode")
            if mode not in ("school", "free", "auto"):
                return {"ok": False, "error": "bad_mode"}
            by_parent = peer == 0
            if peer != 0 and message.get("password"):
                failure = self.host.auth.check(peer, message)
                if failure:
                    return failure
                by_parent = True
            with self.host.lock:
                policy = self.policy_for(uid)
                if policy is None:
                    return {"ok": False, "error": "not_managed"}
                now = self.host.clock.now()
                if mode == "free" and not pam_setup.ready():
                    return {"ok": False, "error": "timer_setup_required"}
                result = policy.set_mode(mode, now, by_parent)
                if result["ok"]:
                    write_json(self.override_path(uid), policy.export_override())
                    self.host.refresh(now)
                return result
        failure = self.host.auth.check(peer, message)
        if failure:
            return failure
        with self.host.lock:
            if uid not in self.managed_uids():
                return {"ok": False, "error": "not_managed"}
            if command == "free-time.unlock":
                now = self.host.clock.now()
                if not self.snapshot(uid, now).get("free_time_expired"):
                    return {"ok": False, "error": "not_expired"}
                result = self.policy_for(uid).set_mode("school", now, True)
                write_json(self.override_path(uid), self.policy_for(uid).export_override())
                self.host.refresh(now)
                return result
            if command == "config.get":
                return {"ok": True, "config": copy.deepcopy(self.config)}
            if command == "config.patch":
                patch = message.get("patch")
                if isinstance(patch, dict) and "school_blocked_domains" in patch:
                    try:
                        patch = {**patch, "school_blocked_domains": normalize_domains(patch["school_blocked_domains"])}
                    except ValueError as error:
                        return {"ok": False, "error": "bad_domains", "message": str(error)}
                if not config.valid_patch(patch):
                    return {"ok": False, "error": "bad_patch"}
                key = self.config["users"][session.username_for(uid)]["profile"]
                updated = config.sanitize_profile({**self.config["profiles"][key], **patch})
                if updated["websites_enabled"] and set(patch) & {"websites_enabled", "school_blocked_domains"}:
                    try:
                        configured = set(updated["school_blocked_domains"])
                        enrolled = {user["profile"] for user in self.config["users"].values()}
                        for name, profile in self.config["profiles"].items():
                            if name in enrolled and name != key and profile["websites_enabled"]:
                                configured.update(profile["school_blocked_domains"])
                        if len(configured) > MAX_DOMAINS:
                            raise ValueError("Use at most 100 different blocked domains across this laptop's profiles.")
                        self.websites.preflight()
                    except ValueError as error:
                        return {"ok": False, "error": "websites_setup", "message": str(error)}
                now = self.host.clock.now()
                # Settle the existing deadline before applying a changed schedule.
                for target in self.managed_uids():
                    self.snapshot(target, now)
                self.config["profiles"][key] = updated
                for target in self.managed_uids():
                    policy = self.policy_for(target)
                    if "blocked_periods" in patch:
                        policy.reschedule(now)
                    policy.revision += 1
                write_json(self.path, self.config)
                self.host.refresh(now)
                return {"ok": True, "profile": key}
        return {"ok": False, "error": "unknown_command"}

    def tick(self, now, elapsed):
        self.websites.reconcile(now)
        for uid in self.managed_uids():
            data = self.snapshot(uid, now)
            self.publish(uid, now)
            if data.get("mode") != "free" or not data.get("free_time_expired"):
                self.last_lock.pop(uid, None)
                continue
            if uid not in self.sessions:
                self.sessions[uid] = session.SessionWatcher(uid)
            watcher = self.sessions[uid].poll()
            if watcher.present and not watcher.locked and now - self.last_lock.get(uid, 0) >= 5:
                if uid not in self.last_lock:
                    session.notify(uid, "Free Time has ended", "Enter the parent password to return to School Mode.")
                self.last_lock[uid] = now
                session.lock(uid, watcher.session_id)

    def next_delay(self, now, maximum):
        for uid in self.managed_uids():
            policy = self.policy_for(uid)
            if policy.mode_override == "free" and not policy.free_expired:
                deadline = min(policy.free_until, policy.mode_override_until)
                maximum = min(maximum, max(0.05, deadline - now))
        return maximum

    def save(self):
        for uid, policy in self.policies.items():
            write_json(self.override_path(uid), policy.export_override())
