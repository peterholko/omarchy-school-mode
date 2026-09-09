"""School schedule and parent-authorized mode policy, without time accounting."""
from datetime import datetime, timedelta
from omarchy_kids.core.periods import covers, active_period

class Policy:
    def __init__(self, profile):
        self.profile = profile
        self.mode_override = None
        self.mode_override_until = 0.0
        self.mode_override_by_parent = False
        self.mode_override_suppresses_schedule = False
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

    def effective_mode(self, now):
        """(mode, reason): school or free, and why."""
        period = self.free_period(now)
        if self.mode_override and now < self.mode_override_until:
            # A free-time override created before school started yields when
            # the schedule begins. Only the parent's explicit exception while
            # that school period was already active suppresses it.
            if self.mode_override != "free" or period is None \
                    or self.mode_override_suppresses_schedule:
                return self.mode_override, ("parent" if self.mode_override_by_parent else "chosen")
        if self.mode_override is not None:
            self.revision += 1
        self.mode_override = None
        self.mode_override_by_parent = False
        self.mode_override_suppresses_schedule = False
        if period is not None:
            return "school", "schedule"
        return "free", "free"

    def set_mode(self, mode, now, by_parent):
        period = self.free_period(now)
        selects_free = mode == "free" or (mode == "auto" and period is None)
        if selects_free and not by_parent:
            refusal = {"ok": False, "error": "parent_required"}
            if period is not None:
                refusal.update({"until": period["end"], "label": period["label"]})
            return refusal
        if mode == "auto":
            self.mode_override = None
            self.mode_override_by_parent = False
            self.mode_override_suppresses_schedule = False
        elif mode == "school":
            self.mode_override = "school"
            self.mode_override_until = self._day_end(now)
            self.mode_override_by_parent = by_parent
            self.mode_override_suppresses_schedule = False
        elif mode == "free":
            self.mode_override = "free"
            self.mode_override_until = self._period_end(period, now) if period else self._day_end(now)
            self.mode_override_by_parent = by_parent
            self.mode_override_suppresses_schedule = period is not None
        else:
            return {"ok": False, "error": "bad_mode"}
        self.revision += 1
        return {"ok": True, **self.mode_status(now)}

    def mode_status(self, now):
        mode, reason = self.effective_mode(now)
        period = self.free_period(now)
        return {"mode": mode, "mode_reason": reason,
                "school_until": period["end"] if period else "",
                "school_label": period["label"] if period else "",
                "school_apps": list(self.profile["school_apps"])}

    def snapshot(self, now):
        return {**self.mode_status(now), "active_period": self.free_period(now), "revision": self.revision}

    def export_override(self):
        return {key: getattr(self, key) for key in ("mode_override", "mode_override_until", "mode_override_by_parent", "mode_override_suppresses_schedule")}

    def restore_override(self, raw, now):
        if not isinstance(raw, dict) or raw.get("mode_override") not in ("school", "free"):
            return
        until = raw.get("mode_override_until", 0)
        if not isinstance(until, (int, float)) or not now < until <= self._day_end(now):
            return
        for key in self.export_override():
            if key in raw:
                setattr(self, key, raw[key])
        self.effective_mode(now)
