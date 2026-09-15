"""Per-account daily practice quotas, committed before a pet is awarded.

The game owns its presentation. This service issues problems, verifies every
intermediate step and owns limits and completion counters. One
outstanding problem per account prevents concurrent windows spending a slot.
"""
from datetime import datetime
import copy
import pwd
import secrets
from ..core import paths, storage
from ..core.game_service import retire_time_rewards
from . import work

OPERATIONS = ("add", "subtract", "multiply", "divide")
LIMITED = ("add", "subtract", "multiply")


def answer_for(problem):
    operation, a, b = (problem.get(key) for key in ("operation", "a", "b"))
    if type(a) is not int or type(b) is not int or operation not in OPERATIONS:
        raise ValueError("invalid problem")
    if operation == "divide":
        if not (10 <= a <= 99 and 2 <= b <= 9 and a % b == 0 and a // b <= 9):
            raise ValueError("use exact two-digit / one-digit table facts")
        return a // b
    small = operation == "multiply" and 1 <= a <= 9 and 1 <= b <= 9
    if not small and not (10 <= a <= 999 and 10 <= b <= 999):
        raise ValueError("invalid operands")
    if operation == "subtract" and a < b:
        raise ValueError("negative subtraction")
    return a + b if operation == "add" else a - b if operation == "subtract" else a * b


class Service:
    def __init__(self, host):
        self.host = host
        self.path = host.layout.config_path.with_name("pawberry.json")
        self.state_dir = host.layout.state_dir / "pawberry"
        self.config = storage.read_json(self.path, {"users": {}})
        self.accounts = {}
        changed = False
        for settings in self.config["users"].values():
            if "screen_time" in settings:
                settings.pop("screen_time")
                changed = True
        if changed:
            storage.write_json(self.path, self.config)

    def managed_uids(self):
        result = []
        for name in self.config["users"]:
            try:
                result.append(pwd.getpwnam(name).pw_uid)
            except KeyError:
                pass
        return result

    def account(self, uid):
        if uid not in self.accounts:
            paths.private_dir(self.state_dir, scrub=False)
            self.accounts[uid] = storage.read_json(self.state_dir / (str(uid) + ".json"),
                {"day": "", "counts": {}, "pending": None, "receipt": None})
        state = self.accounts[uid]
        state.setdefault("receipts", {})
        if state.get("receipt"):
            state["receipts"].setdefault(state["receipt"]["id"], state["receipt"])
        if retire_time_rewards(state):
            self.persist(uid, state)
        today = datetime.fromtimestamp(self.host.clock.now()).date().isoformat()
        # Never reset backwards after a clock or timezone change.
        if today > state["day"]:
            state["day"], state["counts"] = today, {}
            self.persist(uid, state)
        return state

    def persist(self, uid, state):
        storage.write_json(self.state_dir / (str(uid) + ".json"), state)
        self.accounts[uid] = state

    def status(self, uid):
        state = self.account(uid)
        name = pwd.getpwuid(uid).pw_name
        limits = {op: self.config["users"].get(name, {}).get(op) for op in LIMITED}
        counts = {op: state["counts"].get(op, 0) for op in OPERATIONS}
        return {"ok": True, "practice_only": True, "user": name, "day": state["day"], "limits": limits,
                "completed": counts, "remaining": {op: None if limits.get(op) is None
                    else max(0, limits[op] - counts[op]) for op in OPERATIONS}}

    def dispatch(self, peer, message):
        command = message.get("cmd")
        uid = self.host.resolve_uid(peer, message)
        if uid == 0:
            return {"ok": False, "error": "choose_child_user"}
        try:
            name = pwd.getpwuid(uid).pw_name
        except KeyError:
            return {"ok": False, "error": "unknown_user"}
        if command == "users.set":
            if peer != 0 or type(message.get("enabled")) is not bool:
                return {"ok": False, "error": "not_authorized"}
            with self.host.lock:
                config = copy.deepcopy(self.config)
                # Removing the module does not erase a child's practice limits.
                config["users"].setdefault(name, {})
                storage.write_json(self.path, config); self.config = config
                return {"ok": True}
        if command in ("limits.set", "settings.set"):
            patch = message.get("limits", {})
            if "screen_time" in message:
                return {"ok": False, "error": "rewards_removed"}
            if not isinstance(patch, dict) or not patch or set(patch) - set(LIMITED) or any(
                    value is not None and (type(value) is not int or not 0 <= value <= 10000)
                    for value in patch.values()):
                return {"ok": False, "error": "invalid_limits"}
            denied = self.host.auth.check(peer, message)
            if denied:
                return denied
            with self.host.lock:
                config = copy.deepcopy(self.config)
                config["users"].setdefault(name, {}).update(patch)
                storage.write_json(self.path, config)
                self.config = config
                return self.status(uid)
        with self.host.lock:
            if command == "status":
                return self.status(uid)
            if command not in ("begin", "complete"):
                return {"ok": False, "error": "unknown_command"}
            state = copy.deepcopy(self.account(uid))
            if command == "begin":
                problem = message.get("problem")
                try:
                    answer_for(problem if isinstance(problem, dict) else {})
                except ValueError:
                    return {"ok": False, "error": "invalid_problem"}
                operation = problem["operation"]
                status = self.status(uid)
                state = copy.deepcopy(self.account(uid))
                if status["remaining"][operation] == 0:
                    return {**status, "ok": False, "error": "daily_limit", "operation": operation}
                modern = message.get("protocol") == 2
                state["pending"] = work.generate(problem) if modern else {key: problem[key] for key in ("a", "b", "operation")}
                state["pending"]["id"] = secrets.token_hex(16)
                state["pending"].update(protocol=2 if modern else 1, issued_at=self.host.clock.now())
                self.persist(uid, state)
                return {**status, "id": state["pending"]["id"], "problem": {key: state["pending"][key] for key in ("a", "b", "operation")}}
            identifier = message.get("id")
            if isinstance(identifier, str) and identifier in state["receipts"]:
                return {**self.status(uid), "id": identifier, "already_completed": True,
                    "reward_seconds": 0}
            pending = state.get("pending")
            if not pending or identifier != pending["id"]:
                return {"ok": False, "error": "stale_problem"}
            given = message.get("answer")
            if type(given) is not int or given != answer_for(pending):
                return {"ok": False, "error": "incorrect_answer"}
            if pending.get("protocol") == 2:
                if not work.verified(pending, message.get("steps")):
                    return {"ok": False, "error": "incomplete_work"}
                elapsed = self.host.clock.now() - pending["issued_at"]
                if elapsed > 3600 or elapsed < 0:
                    return {"ok": False, "error": "stale_problem"}
                if elapsed < max(1.5, len(message["steps"]) * 0.15):
                    return {"ok": False, "error": "too_fast"}
            status = self.status(uid)
            state = copy.deepcopy(self.account(uid))
            operation = pending["operation"]
            if status["remaining"][operation] == 0:
                return {**status, "ok": False, "error": "daily_limit", "operation": operation}
            state["counts"][operation] = state["counts"].get(operation, 0) + 1
            state["receipt"] = {"id": identifier, "reward_seconds": 0}
            state["pending"] = None
            # Keep recent completions for retries without spending another slot.
            while len(state["receipts"]) >= 256:
                state["receipts"].pop(next(iter(state["receipts"])))
            state["receipts"][identifier] = state["receipt"]
            self.persist(uid, state)
            result = self.status(uid)
            return {**result, "id": identifier, "already_completed": False,
                "reward_seconds": self.account(uid)["receipt"]["reward_seconds"]}

    def tick(self, now, elapsed):
        for uid in set(self.accounts) | set(self.managed_uids()):
            self.account(uid)

    def save(self):
        # Every setting and completion is synchronously committed before reply.
        pass
