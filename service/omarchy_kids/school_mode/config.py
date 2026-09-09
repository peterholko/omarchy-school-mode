"""School-only profiles, schedules, and enrollment."""
from omarchy_kids.core.periods import DAYS
from .defaults import DEFAULT_SCHOOL_APPS, sanitize_school_apps


def sanitize_profile(raw):
    raw = raw if isinstance(raw, dict) else {}
    periods = []
    entries = raw.get("blocked_periods", [])
    for entry in (entries if isinstance(entries, list) else [])[:8]:
        if not isinstance(entry, dict) or entry.get("mode", "free") != "free":
            continue
        try:
            start, end = (normalize_time(entry.get(k)) for k in ("start", "end"))
        except ValueError:
            continue
        if start == end:
            continue
        days = entry.get("days", DAYS)
        days = [d for d in DAYS if d in days] if isinstance(days, list) else list(DAYS)
        periods.append({"label": str(entry.get("label") or "School")[:40], "enabled": bool(entry.get("enabled", False)),
                        "start": start, "end": end, "days": days or list(DAYS), "mode": "free"})
    return {"name": str(raw.get("name") or "Default")[:80], "blocked_periods": periods,
            "school_apps": sanitize_school_apps(raw.get("school_apps"))}


def normalize_time(value):
    if not isinstance(value, str):
        raise ValueError("invalid time")
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("invalid time")
    hour, minute = map(int, parts)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("invalid time")
    return f"{hour:02d}:{minute:02d}"


def sanitize(raw):
    raw = raw if isinstance(raw, dict) else {}
    profiles_raw = raw.get("profiles", {})
    if not isinstance(profiles_raw, dict):
        profiles_raw = {}
    profiles = {k: sanitize_profile(v) for k, v in profiles_raw.items() if isinstance(k, str) and k and len(k) <= 40}
    if not profiles:
        profiles = {"default": sanitize_profile({})}
    active = raw.get("active_profile")
    if not isinstance(active, str) or active not in profiles:
        active = next(iter(profiles))
    enrollments = {}
    for field in ("users", "disabled_users"):
        source = raw.get(field, {})
        result = {}
        for name, value in (source if isinstance(source, dict) else {}).items():
            if not isinstance(name, str) or not name.strip():
                continue
            key = value.get("profile", active) if isinstance(value, dict) else active
            result[name] = {"profile": key if isinstance(key, str) and key in profiles else active}
        enrollments[field] = result
    users = enrollments["users"]

    return {"version": 1, "active_profile": active, "profiles": profiles, "users": users, "disabled_users": enrollments["disabled_users"]}


def valid_patch(patch):
    if not isinstance(patch, dict) or set(patch) - {"name", "school_apps", "blocked_periods"}:
        return False
    if "school_apps" in patch and (not isinstance(patch["school_apps"], list) or any(not isinstance(app, str) for app in patch["school_apps"])):
        return False
    if "blocked_periods" in patch:
        periods = patch["blocked_periods"]
        if not isinstance(periods, list) or len(periods) > 8:
            return False
        for period in periods:
            if not isinstance(period, dict) or period.get("mode", "free") != "free" or not isinstance(period.get("enabled", False), bool):
                return False
            try:
                if normalize_time(period.get("start")) == normalize_time(period.get("end")):
                    return False
            except (ValueError, TypeError):
                return False
            days = period.get("days", DAYS)
            if not isinstance(days, list) or not days or any(day not in DAYS for day in days):
                return False
    return True
