"""Restartable migration from the bundled time/school configuration."""
import copy
import pwd
import time
from datetime import datetime, timedelta
from .storage import locked, read_json, write_json, school_config_path


def split_config(old):
    time_config = copy.deepcopy(old)
    school = {"version": 1, "active_profile": old.get("active_profile", "default"),
              "profiles": {}, "users": copy.deepcopy(old.get("users", {}))}
    for key, profile in time_config.get("profiles", {}).items():
        periods = profile.get("blocked_periods", [])
        if old.get("version", 1) < 2 and profile.get("grace_seconds") == 60:
            profile["grace_seconds"] = 10
        school["profiles"][key] = {"name": profile.get("name", key),
            "blocked_periods": [p for p in periods if p.get("mode") == "free"]}
        if "school_apps" in profile:
            school["profiles"][key]["school_apps"] = profile.pop("school_apps")
        profile["blocked_periods"] = [p for p in periods if p.get("mode", "block") != "free"]
    time_config["version"] = 3
    return time_config, school


def migrate(layout):
    target = layout.config_path
    with locked(target.with_name(".kids-migration.lock")):
        journal = target.with_name(".kids-migration.json")
        pending = read_json(journal)
        if pending is None:
            old = read_json(target)
            if old is None or old.get("version", 1) >= 3:
                return
            after, school = split_config(old)
            existing = read_json(school_config_path(layout))
            if existing is not None:
                # Never overwrite an independently configured school profile.
                for key, value in school["profiles"].items():
                    current = existing.get("profiles", {}).get(key)
                    if current is not None and (not isinstance(current, dict) or any(field in value and value[field] != configured for field, configured in current.items())):
                        raise ValueError("school configuration already exists; resolve the profile conflict before migration")
                    if current is not None:
                        value.update(current)
                for key, value in existing.get("profiles", {}).items():
                    school["profiles"].setdefault(key, value)
                school["users"].update(existing.get("users", {}))
            backup = target.with_name(target.name + ".before-kids-modules")
            if not backup.exists():
                write_json(backup, old)
            pending = {"time": after, "school": school}
            write_json(journal, pending)
        # The journal is durable before either destination changes. Replaying
        # it after an interrupted start is safe: clients cannot connect yet.
        write_json(school_config_path(layout), pending["school"])
        write_json(target, pending["time"])
        # The old daemon kept manual choices only in memory. Carry a visible
        # school restriction into the new persistent policy; never infer a
        # fresh free-time authorization from a stale status file.
        for name in pending["school"].get("users", {}):
            try:
                uid = pwd.getpwnam(name).pw_uid
            except KeyError:
                continue
            status = read_json(layout.status_path(name), {})
            override = layout.state_dir.parent / "school-mode" / str(uid) / "override.json"
            if not override.exists() and status.get("enabled") and status.get("mode") == "school" and status.get("modeReason") in ("chosen", "parent"):
                end = datetime.fromtimestamp(time.time()).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                write_json(override, {"mode_override": "school", "mode_override_until": end.timestamp(),
                                     "mode_override_by_parent": status["modeReason"] == "parent", "mode_override_suppresses_schedule": False})
        journal.unlink()
