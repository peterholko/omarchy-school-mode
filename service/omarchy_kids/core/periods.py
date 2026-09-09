"""Shared clock-window primitives; each feature owns its own periods."""
from datetime import datetime
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

def covers(period, moment, weekday=None):
    start, end = period["start"], period["end"]
    if start == end:
        return False
    if weekday is not None and period.get("days") and weekday not in period["days"]:
        return False
    return start <= moment < end if start < end else moment >= start or moment < end

def active_period(periods, now, mode):
    date = datetime.fromtimestamp(now)
    return next((p for p in periods if p["enabled"] and p.get("mode", "block") == mode and covers(p, date.strftime("%H:%M"), DAYS[date.weekday()])), None)
