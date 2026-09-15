"""Screen-time accounting and operations hosted by the parent core."""
import json
import copy
import math
import os
import pwd
import time
from datetime import datetime
from . import config as config_mod, paths, quiz as quiz_mod, state as state_mod
from omarchy_kids.core import session
from omarchy_kids.core.storage import public_status
TICK_SECONDS = 5
SAVE_EVERY = 30
IDLE_MAX_SECONDS = 4 * 3600
REST_RESET_SECONDS = 300
REFLECTION_LIMIT = 20
def _human_time(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        hours, minutes = seconds // 3600, (seconds % 3600) // 60
        # A whole hour reads as "1h"; the zeroes only earn their place when
        # there are minutes next to them.
        return "%dh" % hours if minutes == 0 else "%dh%02d" % (hours, minutes)
    return "%dm" % (seconds // 60)

class Account:
    def __init__(self, layout, uid, config, owner_uid=None, log=print):
        self.layout = layout
        self.uid = int(uid)
        self.username = session.username_for(uid)
        self.log = log
        self.store = state_mod.Store(layout, self.uid, owner_uid=owner_uid)
        self.watcher = session.SessionWatcher(self.uid)
        self.stats = self.store.load_stats()
        self.meta = self.store.load_meta()

        self.profile_key, self.profile = config_mod.profile_for(config, self.username)
        self.quiz = quiz_mod.Quiz(self.profile["earn"], self.stats)

        self.paused = False
        self.idle_since = None
        self.stretch = 0.0        # unbroken screen time, for the break nudge
        self.rest_since = None
        self.nudged = False
        self.lock_after = None
        self.lock_count = 0
        self.last_lock_ok = False
        self.blocked_since = None
        self.last_save = 0.0
        self.school_snapshot = lambda now: {}

        self.day = None
        self.rollover(time.time())

    def budget_for(self, now):
        return self.profile["budget_minutes"][state_mod.weekday_key(now)] * 60

    def rollover(self, now):
        key = state_mod.day_key(now)
        if self.day is not None and self.day.day == key:
            return False
        if self.day is not None and self.day.dirty:
            self.store.save_day(self.day)
        self.day = self.store.load_day(key, self.budget_for(now), self.profile_key)
        self.lock_after = None
        self.lock_count = 0
        self.blocked_since = None
        return True

    def apply_config(self, config):
        self.profile_key, self.profile = config_mod.profile_for(config, self.username)
        self.quiz.config = self.profile["earn"]
        if self.day is not None:
            wanted = self.budget_for(time.time())
            if self.day.budget != wanted:
                self.day.budget = wanted
                self.day.clamp_bank()
                self.day.dirty = True

    @staticmethod
    def _covers(period, moment, weekday=None):
        start, end = period["start"], period["end"]
        if start == end:
            return False
        days = period.get("days")
        if weekday is not None and isinstance(days, list) and days and weekday not in days:
            return False
        if start < end:
            return start <= moment < end
        # Wraps past midnight, which is the normal shape for a bedtime.
        return moment >= start or moment < end

    def _period(self, now, mode):
        moment = datetime.fromtimestamp(now).strftime("%H:%M")
        weekday = state_mod.weekday_key(now)
        for period in self.profile["blocked_periods"]:
            if period["enabled"] and period.get("mode", "block") == mode \
                    and self._covers(period, moment, weekday):
                return period
        return None

    def blocking_period(self, now):
        """The enabled blocking period covering this moment, or None.

        Returns the period itself rather than a bool, because the panel says
        which one it is: "dinner" and "bedtime" are not the same sentence.
        """
        return self._period(now, "block")

    def school_active(self, now):
        return self.school_snapshot(now).get("mode") == "school"

    def screen_time_exempt(self, now):
        # School never spends the free-time budget. A bedtime restriction
        # still applies, even when the child chooses School Mode herself.
        return self.school_active(now) and self.blocking_period(now) is None

    def next_period(self, now):
        """The enabled period that starts next, for the line under the bar."""
        moment = datetime.fromtimestamp(now).strftime("%H:%M")
        upcoming = [p for p in self.profile["blocked_periods"] if p["enabled"]]
        if not upcoming:
            return None
        later = [p for p in upcoming if p["start"] > moment]
        if later:
            return min(later, key=lambda p: p["start"])
        # Nothing left today, so the first one tomorrow.
        return min(upcoming, key=lambda p: p["start"])

    @property
    def together(self):
        return self.profile["philosophy"] == "together"

    def block_reason(self, now):
        if self.together:
            return None   # nothing blocks: the agreement is a conversation, not a gate
        if self.blocking_period(now) is not None:
            return "bedtime"
        if self.day.remaining <= 0:
            return "empty"
        return None

    @property
    def in_use(self):
        if self.idle_since is not None:
            return False
        return self.watcher.in_use

    def tick(self, now, elapsed, demo=False):
        self.rollover(now)
        self.watcher.poll()
        if self.school_active(now):
            self.quiz.pending = None

        if self.idle_since is not None and now - self.idle_since > IDLE_MAX_SECONDS:
            self.log(f"idle flag for {self.username} expired, counting again")
            self.idle_since = None

        if demo:
            return

        if self.in_use and not self.paused and self.block_reason(now) is None \
                and not self.screen_time_exempt(now):
            step = min(elapsed, TICK_SECONDS * 4)
            self.day.spend(step)
            self.stretch += step
            self.rest_since = None
            if self.together:
                self.nudge(now)
            else:
                self.warn(now)
        else:
            if self.rest_since is None:
                self.rest_since = now
            elif now - self.rest_since >= REST_RESET_SECONDS:
                self.stretch = 0.0
                self.nudged = False

        self.enforce(now)

        if self.day.dirty and now - self.last_save > SAVE_EVERY:
            self.save()

    def nudge(self, now):
        """The together mode's whole voice: information, never a threat.

        One nudge per unbroken stretch, and one note per day when the time
        passes what the family agreed on. Both are plain statements; nothing
        counts down and nothing follows if they are ignored.
        """
        minutes = self.profile["break_nudge_minutes"]
        if minutes > 0 and not self.nudged and self.stretch >= minutes * 60:
            self.nudged = True
            session.notify(self.uid, "Screen Time",
                           "You have been at it for %d minutes straight. A little break?" % minutes,
                           tag="nudge")
        agreement = self.profile["agreement_minutes"]
        if agreement > 0 and not self.day.agreement_noted and self.day.spent >= agreement * 60:
            self.day.agreement_noted = True
            self.day.dirty = True
            session.notify(self.uid, "Screen Time",
                           "Your agreement is about %s of screen time. You are at %s now."
                           % (_human_time(agreement * 60), _human_time(self.day.spent)),
                           tag="agreement")

    def reflections(self):
        out = []
        for entry in self.day.ledger:
            if entry.get("kind") != "reflection":
                continue
            meta = entry.get("meta") or {}
            out.append({"t": entry.get("t", 0), "text": str(meta.get("text", ""))})
        return out[-REFLECTION_LIMIT:]

    def warn(self, now):
        left = self.day.remaining
        for threshold in self.profile["warn_minutes"]:
            if threshold in self.day.warned:
                continue
            if left <= threshold * 60:
                self.day.warned.append(threshold)
                self.day.dirty = True
                body = ("%d minute left." if threshold == 1 else "%d minutes left.") % threshold
                if self.profile["earn"]["enabled"] and self.earn_room() > 0:
                    body += " Earn more with math problems."
                session.notify(self.uid, "Screen Time", body,
                               urgency="critical" if threshold <= 5 else "normal", tag="warn")
                break

    def enforce(self, now):
        reason = self.block_reason(now)
        if self.screen_time_exempt(now):
            reason = None
        if reason is None or self.paused:
            if self.blocked_since is not None:
                self.clear_block()
            return

        if self.blocked_since is None:
            self.blocked_since = now
            self.day.record("blocked", meta={"reason": reason})
            self.save()
            if self.profile["on_empty"] == "notify":
                session.notify(self.uid, "Time's up",
                               self.blocked_headline(now, reason),
                               urgency="critical", tag="empty")

        if self.profile["on_empty"] != "lock":
            return
        if not self.watcher.present:
            return
        if self.watcher.locked:
            self.lock_after = None
            return

        # At zero, Math time is the session: its full-screen overlay owns the
        # keyboard and is the only thing the child can use. Let a real earning
        # session take as long as it takes. If the app or shell disappears,
        # the ordinary post-unlock deadline starts again on this same path.
        # Bedtime is never held off by Math time.
        if reason == "empty" and session.shell_math_open(self.uid) is True:
            self.lock_after = None
            return

        delay, kind = self.lock_delay()
        if self.lock_after is None:
            self.lock_after = now + delay
            headline = self.blocked_headline(now, reason)
            if kind == "after_unlock":
                headline = "There is no time yet."
            session.notify(self.uid, "Time's up",
                           f"{headline} The screen locks in {int(delay)} seconds.",
                           urgency="critical", tag="empty")
        elif now >= self.lock_after:
            used = session.lock(self.uid, self.watcher.session_id)
            self.lock_count += 1
            self.last_lock_ok = bool(used)
            self.lock_after = None
            self.day.record("locked", meta={"reason": reason, "via": used or "failed"})
            self.save()
            self.log(f"locked {self.username} ({reason}) via {used}")

    def lock_delay(self):
        """How long before the screen goes on the lock, and why that long.

        The three cases are genuinely different. The first is the child being
        told to wrap up. A retry after a lock that did not take should come
        round quickly. But a session that is unlocked again while the budget is
        zero was unlocked by somebody holding the account password, and on a
        machine set up for a child that is the parent, so they get room to open
        the panel and hand out minutes instead of racing a countdown.
        """
        if self.lock_count == 0:
            return self.profile["grace_seconds"], "first"
        if not self.last_lock_ok:
            return self.profile["relock_seconds"], "retry"
        return self.profile["unlock_grace_seconds"], "after_unlock"

    def clear_block(self):
        """Time was added, so whatever was counting down to the lock stops now.

        The next tick would do this anyway, but a panel refreshes right after
        the click and would otherwise still show a lock coming.
        """
        self.blocked_since = None
        self.lock_after = None
        self.lock_count = 0
        self.last_lock_ok = False

    def save(self):
        self.store.save_day(self.day)
        self.store.save_stats(self.stats)
        self.meta["last_logical"] = time.time()
        self.store.save_meta(self.meta)
        self.last_save = time.time()
        self.publish_status(time.time())

    def publish_status(self, now):
        try:
            path = self.layout.status_path(self.username)
            earn = self.profile["earn"]
            payload = {
                "schemaVersion": 1,
                "updatedAt": now,
                "enabled": True,
                "school": self.school_active(now),
                "paused": self.paused,
                "budget": max(0, int(self.day.remaining)),
                "earnedToday": int(math.ceil(self.day.earned / 60)),
                "usedToday": int(self.day.spent),
                "cap": earn["daily_cap_minutes"],
                "rate": round(earn["set_minutes"] / max(1, earn["questions_per_set"]), 2),
                "creditSeconds": config_mod.seconds_per_correct(earn),
                "questions": earn["questions_per_set"],
                "sessionMinutes": earn["set_minutes"],
                "level": earn["level"],
                "earning": bool(earn["enabled"]) and not self.together and not self.school_active(now) and self.earn_room() > 0,
                "phase": self.phase(now),
            }
            payload.update(self.mode_status(now))
            payload["schoolApps"] = payload.pop("school_apps")
            payload["modeReason"] = payload.pop("mode_reason")
            payload["schoolUntil"] = payload.pop("school_until")
            payload["schoolLabel"] = payload.pop("school_label")
            public_status(self.layout, self.username, "time", payload)
        except OSError as exc:
            self.log(f"could not publish status for {self.username}: {exc}")

    def clear_status(self):
        try:
            public_status(self.layout, self.username, "time", {"schemaVersion": 1, "enabled": False})
        except OSError:
            pass

    def earn_room(self):
        cap = self.profile["earn"]["daily_cap_minutes"] * 60
        return max(0, cap - self.day.earned)

    def activity_reward_reason(self, now):
        if self.school_active(now):
            return "school_mode_active"
        if self.blocking_period(now):
            return "bedtime"
        if self.together or not self.profile["earn"]["enabled"]:
            return "earning_disabled"
        if self.paused or self.watcher.locked:
            return "screen_time_paused"
        if self.earn_room() <= 0:
            return "daily_cap_reached"
        return ""

    def credit_activity(self, activity, identifier, seconds, daily_cap, label, now):
        """Internal verified-completion hook; never exposed as a client command.

        The caller holds the host lock and durably records its completion
        before calling. Save credit and its receipt together before changing
        the live balance, so a failed write or retried completion cannot mint
        duplicate minutes. Activity credits share the normal earning cap.
        """
        previous = self.day.activity_rewards.get(activity, {})
        if previous.get("last_id") == identifier:
            return previous["last_reward_seconds"]
        earned = previous.get("earned_seconds", 0)
        reward = 0 if self.activity_reward_reason(now) else min(
            seconds, self.earn_room(), max(0, daily_cap - earned))
        candidate = copy.deepcopy(self.day)
        candidate.add("earn", reward, {"source": activity, "q": label})
        candidate.activity_rewards[activity] = {"earned_seconds": earned + reward,
            "last_id": identifier, "last_reward_seconds": reward}
        self.store.save_day(candidate)
        self.day = candidate
        if reward > 0 and self.day.remaining > 0:
            self.clear_block()
        self.publish_status(now)
        return reward

    def quiz_next(self, now, choices=0):
        if self.school_active(now):
            self.quiz.pending = None
            return {"ok": False, "error": "school_mode_active"}
        earn = self.profile["earn"]
        if self.together or not earn["enabled"]:
            return {"ok": False, "error": "earning_disabled"}
        if self.earn_room() <= 0:
            return {"ok": False, "error": "daily_cap_reached",
                    "cap_minutes": earn["daily_cap_minutes"]}
        question = self.quiz.next_question(now, game=choices == 6)
        if question is None:
            return {"ok": False, "error": "no_questions"}
        reward = min(config_mod.seconds_per_correct(earn), self.earn_room())
        public = question.public(reward, earn["question_timeout_seconds"])
        if choices == 6:
            public["choices"] = question.choices()
        return {"ok": True, "question": public,
                "earn_room_seconds": self.earn_room(),
                "questions_per_set": earn["questions_per_set"],
                "set_minutes": earn["set_minutes"], "level": earn["level"]}

    def quiz_answer(self, question_id, given, now):
        if self.school_active(now):
            self.quiz.pending = None
            return {"ok": False, "error": "school_mode_active"}
        earn = self.profile["earn"]
        if self.together or not earn["enabled"]:
            self.quiz.pending = None
            return {"ok": False, "error": "earning_disabled"}
        verdict = self.quiz.answer(question_id, given, now)
        if not verdict.get("ok"):
            return verdict
        reward = 0
        if verdict["correct"]:
            reward = min(config_mod.seconds_per_correct(earn), self.earn_room())
            if reward > 0:
                self.day.add("earn", reward, {"q": verdict["text"]})
                if self.day.remaining > 0:
                    self.clear_block()
            self.day.correct += 1
            self.day.dirty = True
        else:
            # A miss is worth keeping too. A list that only shows what went
            # right says nothing about which tables are still hard, and the
            # child gets to see their own afternoon rather than a scoreboard.
            self.day.record("miss", meta={"q": verdict.get("text", ""),
                                          "given": verdict.get("given"),
                                          "answer": verdict.get("answer")})
        self.store.save_stats(self.stats)
        self.save()
        verdict.update({
            "reward_seconds": reward,
            "earn_room_seconds": self.earn_room(),
            "remaining_seconds": max(0, self.day.remaining),
        })
        return verdict

    def blocked_headline(self, now, reason):
        """What to call the block in a notification, in the family's words."""
        if reason == "empty":
            return "Today's screen time is used up."
        period = self.blocking_period(now)
        label = period["label"].strip().lower() if period else "a quiet time"
        return f"It is {label}."

    def phase(self, now):
        reason = self.block_reason(now)
        if self.paused:
            return "paused"
        if self.screen_time_exempt(now):
            return "school"
        if reason == "bedtime":
            return "bedtime"
        if reason == "empty":
            return "empty"
        if not self.in_use:
            return "idle"
        return "running"

    def status(self, now):
        reason = self.block_reason(now)
        phase = self.phase(now)
        earn = self.profile["earn"]
        payload = {
            "ok": True,
            "user": self.username,
            "profile": self.profile_key,
            "profile_name": self.profile["name"],
            "philosophy": self.profile["philosophy"],
            "agreement_text": self.profile["agreement_text"],
            "agreement_minutes": self.profile["agreement_minutes"],
            "break_nudge_minutes": self.profile["break_nudge_minutes"],
            "stretch_seconds": int(self.stretch),
            "reflections": self.reflections(),
            "day": self.day.day,
            "phase": phase,
            "counting": phase == "running",
            "remaining_seconds": max(0, self.day.remaining),
            "budget_seconds": self.day.budget,
            "spent_seconds": self.day.spent,
            "earned_seconds": self.day.earned,
            "granted_seconds": self.day.granted,
            "correct_answers": self.day.correct,
            "warn_seconds": [m * 60 for m in self.profile["warn_minutes"]],
            "locked": self.watcher.locked,
            "session_present": self.watcher.present,
            "lock_in_seconds": (max(0, int(self.lock_after - now))
                                if self.lock_after and reason and not self.paused else None),
            "blocked_periods": self.profile["blocked_periods"],
            "blocked_label": (self.blocking_period(now) or {}).get("label", ""),
            "free_label": (self.free_period(now) or {}).get("label", ""),
            "next_block": self.next_period(now),
            "budget_minutes": dict(self.profile["budget_minutes"]),
            "on_empty": self.profile["on_empty"],
            "earn": {
                "enabled": earn["enabled"],
                "level": earn["level"],
                "questions_per_set": earn["questions_per_set"],
                "set_minutes": earn["set_minutes"],
                "seconds_per_correct": config_mod.seconds_per_correct(earn),
                "cap_seconds": earn["daily_cap_minutes"] * 60,
                "room_seconds": self.earn_room(),
                "events": self.earn_events(),
            },
        }
        payload.update(self.mode_status(now))
        return payload

    def earn_events(self, limit=50):
        """Today's sums, oldest first, for the panel's tally list.

        Both the rewards and the misses, because the misses are the half that
        says which tables are still hard.
        """
        out = []
        for entry in self.day.ledger:
            kind = entry.get("kind")
            if kind not in ("earn", "miss"):
                continue
            meta = entry.get("meta") or {}
            row = {"t": entry.get("t", 0),
                   "kind": kind,
                   "seconds": int(entry.get("seconds", 0)),
                   "q": str(meta.get("q", ""))}
            if kind == "miss":
                row["given"] = meta.get("given")
                row["answer"] = meta.get("answer")
            out.append(row)
        return out[-limit:]

    def free_period(self, now):
        return self.school_snapshot(now).get("active_period")

    def mode_status(self, now):
        policy = self.school_snapshot(now)
        return {"mode": policy.get("mode", "free"), "mode_reason": policy.get("mode_reason", "free"),
                "school_apps": policy.get("school_apps", []), "school_until": policy.get("school_until", ""),
                "school_label": policy.get("school_label", "")}

DEMO_STATUS = {
    "ok": True,
    "user": "sam",
    "profile": "sam",
    "profile_name": "Sam",
    "philosophy": "limits",
    "agreement_text": "",
    "agreement_minutes": 0,
    "break_nudge_minutes": 45,
    "stretch_seconds": 1455,
    "reflections": [],
    "pin_set": True,
    "day": "2026-09-02",
    "phase": "running",
    "counting": True,
    "remaining_seconds": 2745,
    "budget_seconds": 3600,
    "spent_seconds": 1455,
    "earned_seconds": 600,
    "granted_seconds": 0,
    "correct_answers": 20,
    "warn_seconds": [900, 300, 60],
    "locked": False,
    "session_present": True,
    "lock_in_seconds": None,
    "blocked_periods": [
        {"label": "School", "enabled": True, "start": "08:30", "end": "15:00", "days": ["mon", "tue", "wed", "thu", "fri"], "mode": "free"},
        {"label": "Dinner", "enabled": True, "start": "18:00", "end": "18:45", "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "mode": "block"},
        {"label": "Bedtime", "enabled": True, "start": "20:00", "end": "07:00", "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "mode": "block"},
    ],
    "blocked_label": "",
    "free_label": "",
    "next_block": {"label": "Dinner", "enabled": True, "start": "18:00", "end": "18:45", "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "mode": "block"},
    "on_empty": "lock",
    "earn": {
        "enabled": True,
        "level": "grade5",
        "questions_per_set": 10,
        "set_minutes": 30,
        "seconds_per_correct": 180,
        "cap_seconds": 7200,
        "room_seconds": 6600,
        "events": [
            {"t": 1788470000.0, "kind": "earn", "seconds": 180, "q": "7 × 8"},
            {"t": 1788470100.0, "kind": "miss", "seconds": 0, "q": "8 × 7",
             "given": 54, "answer": 56},
            {"t": 1788470200.0, "kind": "earn", "seconds": 180, "q": "54 ÷ 6"},
            {"t": 1788470300.0, "kind": "earn", "seconds": 180, "q": "9 × 6"},
        ],
    },
    "demo": True,
}

DEMO_PASSWORD = "1234"

DEMO_HISTORY = [
    {"day": "2026-09-02", "budget_seconds": 3600, "spent_seconds": 1455, "earned_seconds": 600,
     "granted_seconds": 0, "correct_answers": 20},
    {"day": "2026-09-01", "budget_seconds": 3600, "spent_seconds": 4080, "earned_seconds": 480,
     "granted_seconds": 0, "correct_answers": 16},
    {"day": "2026-08-31", "budget_seconds": 5400, "spent_seconds": 5400, "earned_seconds": 900,
     "granted_seconds": 900, "correct_answers": 30},
    {"day": "2026-08-30", "budget_seconds": 5400, "spent_seconds": 3120, "earned_seconds": 0,
     "granted_seconds": 0, "correct_answers": 0},
    {"day": "2026-08-29", "budget_seconds": 3600, "spent_seconds": 3600, "earned_seconds": 300,
     "granted_seconds": 600, "correct_answers": 10},
]

class Service:
    def __init__(self, host):
        self.host = host
        self.layout = host.layout
        self.lock = host.lock
        self.log = host.log
        self.clock = host.clock
        self.config = config_mod.load(self.layout)
        self.accounts = {}
        self.resolve_uid = host.resolve_uid

    def check_parent(self, uid, account, message, command=""):
        return self.host.auth.check(uid, message, demo=bool(self.config.get("demo")))

    def managed_uids(self):
        if self.layout.mode in ("system", "test"):
            uids = []
            for name in self.config.get("users", {}):
                try:
                    uids.append(pwd.getpwnam(name).pw_uid)
                except KeyError:
                    self.log(f"config lists unknown account: {name}")
            return uids
        return [os.getuid()]

    def account_for(self, uid):
        with self.lock:
            if uid in self.accounts:
                return self.accounts[uid]
            if uid not in self.managed_uids():
                return None
            if self.layout.mode == "system" and uid == 0:
                return None
            # The state is root's in every layout: in system mode the kid
            # must not be able to write her own day, and a root-owned
            # directory is what root creates.
            account = Account(self.layout, uid, self.config, owner_uid=None, log=self.log)
            account.school_snapshot = lambda now: self.host.school_snapshot(uid, now)
            floor = account.meta.get("last_logical")
            if floor and floor > self.clock.now():
                self.clock.logical = float(floor)
                self.log("stored time is ahead of the system clock, following the stored one")
            self.accounts[uid] = account
            return account

    def status_for(self, account):
        if self.config.get("demo"):
            return dict(DEMO_STATUS)
        if account is None:
            return {"ok": False, "error": "not_managed"}
        with self.lock:
            payload = account.status(self.clock.now())
            payload["pin_set"] = True
            return payload

    def dispatch(self, uid, message):
        command = str(message.get("cmd", ""))
        peer = uid
        uid = self.resolve_uid(uid, message)
        account = self.account_for(uid)
        now = self.clock.now()
        demo = bool(self.config.get("demo"))

        if command == "users":
            # Root's: which accounts the daemon manages, from the config.
            if peer != 0:
                return {"ok": False, "error": "not_allowed"}
            return {"ok": True, "users": sorted(self.config.get("users", {}).keys()),
                    "mode": self.layout.mode}

        if command == "users.set":
            if peer != 0:
                return {"ok": False, "error": "not_allowed"}
            name = str(message.get("user", ""))
            try:
                target_uid = pwd.getpwnam(name).pw_uid
            except KeyError:
                return {"ok": False, "error": "unknown_user"}
            if target_uid == 0:
                return {"ok": False, "error": "not_allowed"}
            enabled = bool(message.get("enabled", True))
            with self.lock:
                users = dict(self.config.get("users", {}))
                profiles = self.config["profiles"]
                if enabled:
                    if name not in users:
                        key = self.config["disabled_users"].pop(name, {"profile": name})["profile"]
                        if key not in profiles:
                            profiles[key] = config_mod.sanitize_profile(dict(profiles.get(self.config["active_profile"], {}), name=name))
                        users[name] = {"profile": key}
                else:
                    previous = users.pop(name, None)
                    if previous is not None:
                        self.config["disabled_users"][name] = previous
                self.config["users"] = users
                merged = config_mod.sanitize(self.config)
                merged["demo"] = bool(self.config.get("demo"))
                self.config = merged
                config_mod.save(self.layout, merged)
                if not enabled:
                    for existing_uid, existing in list(self.accounts.items()):
                        if existing.username == name:
                            existing.save()
                            existing.clear_status()
                            del self.accounts[existing_uid]
                for existing in self.accounts.values():
                    existing.apply_config(merged)
                if not enabled:
                    public_status(self.layout, name, "time", {"schemaVersion": 1, "enabled": False})
                return {"ok": True, "users": sorted(users.keys())}

        if command == "quiz.practice":
            level = str(message.get("level", "grade5"))
            if level not in config_mod.LEVELS:
                return {"ok": False, "error": "bad_level"}
            return {"ok": True, **quiz_mod.practice(level)}

        if command == "ping":
            return {"ok": True, "mode": self.layout.mode, "demo": demo}

        if command == "status":
            return self.status_for(account)

        if command == "history":
            if demo:
                return {"ok": True, "days": list(DEMO_HISTORY)}
            if account is None:
                return {"ok": False, "error": "not_managed"}
            days = message.get("days", 14)
            days = days if isinstance(days, int) and 1 <= days <= 366 else 14
            with self.lock:
                return {"ok": True, "days": account.store.history(days)}

        if account is None:
            return {"ok": False, "error": "not_managed"}

        if command == "quiz.next":
            choices = message.get("choices", 0)
            if type(choices) is not int or choices not in (0, 6):
                return {"ok": False, "error": "invalid_choices"}
            if demo:
                return {"ok": True, "question": {"id": "demo", "text": "7 × 8", "kind": "table",
                                                 "reward_seconds": 180, "timeout_seconds": 1800,
                                                 **({"choices": [48, 63, 54, 72, 56, 42]} if choices else {})},
                        "earn_room_seconds": 6600, "questions_per_set": 10, "set_minutes": 30, "level": "grade5"}
            with self.lock:
                return account.quiz_next(now, choices)

        if command == "quiz.answer":
            if demo:
                return {"ok": True, "correct": True, "text": "7 × 8", "answer": 56,
                        "given": 56, "seconds_taken": 3.4, "reward_seconds": 180,
                        "earn_room_seconds": 6420, "remaining_seconds": 2925}
            with self.lock:
                return account.quiz_answer(message.get("id"), message.get("answer"), now)

        if command == "day":
            # One day's ledger, today by default, for the parent's report.
            with self.lock:
                day = str(message.get("day") or account.day.day)
                if day == account.day.day:
                    payload = account.day.to_json()
                else:
                    payload = account.store.load_day(day, 0, account.profile_key).to_json()
                return {"ok": True, "user": account.username, "day": payload,
                        "cap_minutes": account.profile["earn"]["daily_cap_minutes"]}

        if command == "idle":
            with self.lock:
                account.idle_since = now if message.get("value") else None
                return {"ok": True, "idle": account.idle_since is not None}

        if command == "reflect":
            # The child's own words about their own time. No PIN: the journal
            # belongs to the child, the parent only sees what gets shown.
            text = str(message.get("text", "")).strip()[:280]
            if not text:
                return {"ok": False, "error": "empty"}
            with self.lock:
                account.day.record("reflection", meta={"text": text})
                account.save()
                return {"ok": True, "reflections": account.reflections()}

        if command == "reflect.forget":
            # Taking a note back is the child's too, so it asks for no PIN
            # either. Matched on the entry's own timestamp: the panel hands
            # back what it was given rather than an index into a list that
            # may have grown since.
            try:
                stamp = round(float(message.get("t", 0)), 1)
            except (TypeError, ValueError):
                return {"ok": False, "error": "bad_timestamp"}
            with self.lock:
                before = len(account.day.ledger)
                account.day.ledger = [
                    entry for entry in account.day.ledger
                    if not (entry.get("kind") == "reflection"
                            and round(float(entry.get("t", 0)), 1) == stamp)
                ]
                if len(account.day.ledger) == before:
                    return {"ok": False, "error": "no_such_note"}
                account.day.dirty = True
                account.save()
                return {"ok": True, "reflections": account.reflections()}

        # everything below changes the budget, so it is the parent's to do
        refusal = self.check_parent(peer, account, message, command)
        if refusal:
            return refusal
        if demo and command in ("grant", "pause", "lock"):
            return {"ok": True, "demo": True, "note": "demo mode, nothing changed"}

        now = self.clock.now()
        if command == "grant":
            minutes = message.get("minutes")
            if not isinstance(minutes, int) or not (-600 <= minutes <= 600):
                return {"ok": False, "error": "bad_minutes"}
            with self.lock:
                applied = account.day.add("grant", minutes * 60, {"by": "parent"})
                if account.day.remaining > 0:
                    account.clear_block()
                if minutes > 0:
                    account.day.warned = [w for w in account.day.warned
                                          if w * 60 >= account.day.remaining]
                account.save()
                if applied > 0:
                    note = f"You got {applied // 60} extra minutes."
                elif applied < 0:
                    note = f"{math.ceil(abs(applied) / 60)} minutes were taken away."
                else:
                    note = "There was no screen time left to take away."
                session.notify(account.uid, "Screen Time", note, tag="grant")
                payload = account.status(now)
                payload["applied_seconds"] = applied
                return payload

        if command == "pause":
            with self.lock:
                account.paused = bool(message.get("value", True))
                account.day.record("pause" if account.paused else "resume")
                account.save()
                return account.status(now)

        if command == "lock":
            with self.lock:
                used = session.lock(account.uid, account.watcher.session_id)
                account.day.record("locked", meta={"reason": "parent", "via": used or "failed"})
                account.save()
                return {"ok": bool(used), "via": used}

        if command == "config.get":
            with self.lock:
                safe = json.loads(json.dumps(self.config))
                safe["pin"] = bool(safe.get("pin"))
                return {"ok": True, "config": safe, "mode": self.layout.mode}

        if command == "config.patch":
            # A partial change to this account's own profile, so the settings
            # window can flip one switch without resending the whole config.
            patch = message.get("patch")
            if not isinstance(patch, dict):
                return {"ok": False, "error": "bad_patch"}
            with self.lock:
                key = account.profile_key
                current = json.loads(json.dumps(self.config["profiles"].get(key, {})))
                self.config["profiles"][key] = config_mod.sanitize_profile(
                    config_mod.deep_merge(current, patch))
                merged = config_mod.sanitize(self.config)
                merged["demo"] = bool(self.config.get("demo"))
                self.config = merged
                config_mod.save(self.layout, merged)
                for existing in self.accounts.values():
                    existing.apply_config(merged)
                    existing.publish_status(now)
                return {"ok": True, "profile": key}

        if command == "config.set":
            incoming = message.get("config")
            if not isinstance(incoming, dict):
                return {"ok": False, "error": "bad_config"}
            with self.lock:
                merged = config_mod.sanitize(incoming)
                merged["demo"] = bool(incoming.get("demo", self.config.get("demo")))
                self.config = merged
                config_mod.save(self.layout, merged)
                for existing_uid, existing in list(self.accounts.items()):
                    if existing_uid not in self.managed_uids():
                        existing.save()
                        existing.clear_status()
                        del self.accounts[existing_uid]
                    else:
                        existing.apply_config(merged)
                return {"ok": True, "config_applied": True}

        if command == "demo":
            with self.lock:
                self.config["demo"] = bool(message.get("value"))
                config_mod.save(self.layout, self.config)
                return {"ok": True, "demo": self.config["demo"]}

        return {"ok": False, "error": "unknown_command", "cmd": command}

    def tick(self, now, elapsed):
        failures = []
        for uid in self.managed_uids():
            try:
                account = self.account_for(uid)
                account.tick(now, elapsed, demo=bool(self.config.get("demo")))
                account.publish_status(now)
            except Exception as exc:
                self.log(f"could not set up uid {uid} or tick screen time: {exc}")
                failures.append(uid)
        if failures:
            raise RuntimeError("screen-time accounts failed: " + str(failures))

    def save(self):
        for account in self.accounts.values():
            account.save()
