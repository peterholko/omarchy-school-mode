"""School policy service; no import or requirement for the time module."""
import copy
import os
import pwd
from . import config
from .policy import Policy
from omarchy_kids.core import session
from omarchy_kids.core.storage import read_json, write_json, school_config_path, public_status


class Service:
    def __init__(self, host):
        self.host = host
        self.path = school_config_path(host.layout)
        self.config = config.sanitize(read_json(self.path, {}))
        self.policies = {}

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
        return policy.snapshot(now) if policy else {}

    def status(self, uid, now):
        policy = self.policy_for(uid)
        if policy is None:
            return {"ok": False, "error": "not_managed", "enabled": False, "schemaVersion": 1}
        return {"ok": True, "enabled": True, "schemaVersion": 1,
                **policy.snapshot(now), "blocked_periods": policy.profile["blocked_periods"]}

    def publish(self, uid, now):
        data = self.status(uid, now)
        public = {"schemaVersion": 1, "enabled": data.get("enabled", False), "updatedAt": now,
                  "revision": data.get("revision", 0), "mode": data.get("mode", "free"),
                  "modeReason": data.get("mode_reason", ""), "schoolApps": data.get("school_apps", []),
                  "schoolUntil": data.get("school_until", ""), "schoolLabel": data.get("school_label", ""),
                  "blockedPeriods": data.get("blocked_periods", [])}
        public_status(self.host.layout, session.username_for(uid), "school-mode", public)

    def dispatch(self, peer, message):
        uid = self.host.resolve_uid(peer, message)
        command = message.get("cmd")
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
            if command == "config.get":
                return {"ok": True, "config": copy.deepcopy(self.config)}
            if command == "config.patch":
                patch = message.get("patch")
                if not config.valid_patch(patch):
                    return {"ok": False, "error": "bad_patch"}
                key = self.config["users"][session.username_for(uid)]["profile"]
                self.config["profiles"][key] = config.sanitize_profile({**self.config["profiles"][key], **patch})
                for policy in self.policies.values():
                    policy.revision += 1
                write_json(self.path, self.config)
                self.host.refresh(self.host.clock.now())
                return {"ok": True, "profile": key}
        return {"ok": False, "error": "unknown_command"}

    def tick(self, now, elapsed):
        for uid in self.managed_uids():
            self.publish(uid, now)

    def save(self):
        for uid, policy in self.policies.items():
            write_json(self.override_path(uid), policy.export_override())
