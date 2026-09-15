"""School schedules and durable, parent-granted Free Time allowances."""
import math
from datetime import datetime, timedelta
from omarchy_kids.core.periods import active_period, DAYS


class Policy:
    def __init__(self, profile):
        self.profile = profile
        self.mode_override = None
        self.mode_override_until = 0.0
        self.mode_override_by_parent = False
        self.mode_override_suppresses_schedule = False
        self.free_until = 0.0
        self.free_expired = False
        self.last_seen = 0.0
        self.revision = 0

    def free_period(self, now):
        return active_period(self.profile["blocked_periods"], now, "free")

    @staticmethod
    def _period_end(period, now):
        moment = datetime.fromtimestamp(now)
        hour, minute = map(int, period["end"].split(":"))
        end = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if end <= moment:
            end += timedelta(days=1)
        return end.timestamp()

    @staticmethod
    def _day_end(now):
        return (datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()

    def next_school_start(self, now):
        moment = datetime.fromtimestamp(now)
        starts = [now + 8 * 86400]  # Beyond any allowed Free Time duration.
        for offset in range(8):
            day = moment + timedelta(days=offset)
            for period in self.profile['blocked_periods']:
                if not period['enabled'] or DAYS[day.weekday()] not in period['days']:
                    continue
                hour, minute = map(int, period['start'].split(':'))
                start = day.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
                if start > now:
                    starts.append(start)
        return min(starts)

    def reschedule(self, now):
        if self.mode_override == 'free' and not self.free_expired:
            self.mode_override_until = (now if self.free_period(now) and not self.mode_override_suppresses_schedule
                                        else self.next_school_start(now))

    def effective_mode(self, now):
        self.last_seen = max(self.last_seen, now)
        now = self.last_seen
        # Expiry survives mode requests and reboot until a parent returns to School.
        if self.free_expired:
            return "free", "expired"
        period = self.free_period(now)
        if self.mode_override == "free" and self.free_until:
            school_due = now >= self.mode_override_until and self.mode_override_until <= self.free_until
            if school_due:
                self.free_until = 0.0
                self.mode_override = None
                self.revision += 1
            elif now >= self.free_until:
                self.free_expired = True
                self.revision += 1
                return "free", "expired"
            else:
                return "free", "parent"
        if self.mode_override == "school" and now < self.mode_override_until:
            return "school", "parent" if self.mode_override_by_parent else "chosen"
        if period is not None:
            return "school", "schedule"
        # Finishing school hours never grants free minutes without a parent.
        return "school", "ready"

    def set_mode(self, mode, now, by_parent):
        self.effective_mode(now)
        now = self.last_seen
        if mode not in ("school", "free", "auto"):
            return {"ok": False, "error": "bad_mode"}
        if (mode == "free" or self.free_expired) and not by_parent:
            return {"ok": False, "error": "parent_required"}
        if self.free_expired and mode == "free":
            return {"ok": False, "error": "unlock_to_school"}
        period = self.free_period(now)
        self.free_expired = False
        self.free_until = 0.0
        self.mode_override_by_parent = bool(by_parent)
        self.mode_override_suppresses_schedule = False
        self.mode_override = None if mode == "auto" else mode
        self.mode_override_until = self._day_end(now)
        if mode == "free":
            self.free_until = now + self.profile["free_time_minutes"] * 60
            self.mode_override_until = self.next_school_start(now)
            self.mode_override_suppresses_schedule = period is not None
        self.revision += 1
        return {"ok": True, **self.mode_status(now)}

    def mode_status(self, now):
        mode, reason = self.effective_mode(now)
        period = self.free_period(self.last_seen)
        remaining = max(0, math.ceil(self.free_until - self.last_seen)) if mode == "free" and not self.free_expired else 0
        return {"mode": mode, "mode_reason": reason,
                "school_until": period["end"] if period else "",
                "school_label": period["label"] if period else "",
                "school_apps": list(self.profile["school_apps"]),
                "free_time_minutes": self.profile["free_time_minutes"],
                "free_time_remaining_seconds": remaining,
                "free_time_expired": self.free_expired,
                "free_time_deadline": self.free_until if mode == "free" else 0.0}

    def snapshot(self, now):
        return {**self.mode_status(now), "active_period": self.free_period(self.last_seen), "revision": self.revision}

    def export_override(self):
        fields = ("mode_override", "mode_override_until", "mode_override_by_parent", "mode_override_suppresses_schedule",
                  "free_until", "free_expired", "last_seen", "revision")
        return {"timer_version": 1, **{key: getattr(self, key) for key in fields}}

    def restore_override(self, raw, now):
        if not isinstance(raw, dict):
            return
        if raw.get("timer_version") != 1:
            # Preserve School choices. Old unlimited Free Time is not a new grant.
            if raw.get("mode_override") == "school":
                self.set_mode("school", now, raw.get("mode_override_by_parent") is True)
            return
        if raw.get("mode_override") not in (None, "school", "free"):
            return
        for key in ("mode_override_until", "free_until", "last_seen"):
            value = raw.get(key, 0.0)
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                return
        self.mode_override = raw.get("mode_override")
        for key in ("mode_override_until", "free_until", "last_seen"):
            setattr(self, key, float(raw.get(key, 0.0)))
        for key in ("mode_override_by_parent", "mode_override_suppresses_schedule", "free_expired"):
            setattr(self, key, raw.get(key) is True)
        self.revision = raw.get("revision", 0) if type(raw.get("revision")) is int else 0
        self.effective_mode(now)
