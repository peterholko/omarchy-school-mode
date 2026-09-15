"""Shared lifecycle for optional game-owned challenge verifiers."""
import copy
from datetime import datetime
import pwd
import secrets
from . import paths, storage


def retire_time_rewards(state):
    """Keep completion history, but never retry an old time-credit request."""
    changed = False
    for receipt in state.get("receipts", {}).values():
        if receipt.get("reward_seconds") is None:
            receipt.update(reward_seconds=0, reward_reason="rewards_removed")
            changed = True
    if state.get("receipt"):
        state["receipt"] = state["receipts"].get(state["receipt"]["id"], state["receipt"])
    return changed


class GameService:
    module = ""

    def __init__(self, host):
        self.host = host
        self.path = host.layout.config_path.with_name(self.module + ".json")
        self.state_dir = host.layout.state_dir / self.module
        self.config = storage.read_json(self.path, {"users": {}})
        self.accounts = {}

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
            self.accounts[uid] = storage.read_json(self.state_dir / (str(uid) + ".json"), {"pending": None, "receipts": {}})
            if retire_time_rewards(self.accounts[uid]):
                self.persist(uid, self.accounts[uid])
        return self.accounts[uid]

    def persist(self, uid, state):
        storage.write_json(self.state_dir / (str(uid) + ".json"), state)
        self.accounts[uid] = state

    def status(self, uid):
        state = self.account(uid)
        # Older clients see rewards as unavailable. The retained verifier can
        # still validate a challenge, but has no screen-time transport.
        return {"ok": True, "practice_only": True, "available": False,
            "active": False, "enabled": False, "reason": "rewards_removed",
            "receipts": [{"id": r["id"], "reward_seconds": 0}
                for r in list(state["receipts"].values())[-256:]]}

    def dispatch(self, peer, message):
        uid = self.host.resolve_uid(peer, message)
        try:
            name = pwd.getpwuid(uid).pw_name
        except KeyError:
            return {"ok": False, "error": "unknown_user"}
        if uid == 0:
            return {"ok": False, "error": "choose_child_user"}
        command = message.get("cmd")
        with self.host.lock:
            if command == "users.set":
                if peer != 0 or type(message.get("enabled")) is not bool:
                    return {"ok": False, "error": "not_authorized"}
                config = copy.deepcopy(self.config)
                if message["enabled"]:
                    config["users"].setdefault(name, {})
                else:
                    config["users"].pop(name, None)
                storage.write_json(self.path, config); self.config = config
                return {"ok": True}
            if name not in self.config["users"]:
                return {"ok": False, "error": "not_managed"}
            if command == "status":
                return self.status(uid)
            if command not in ("begin", "complete"):
                return {"ok": False, "error": "unknown_command"}
            state = copy.deepcopy(self.account(uid))
            now = self.host.clock.now()
            if command == "begin":
                try:
                    challenge = self.challenge(message)
                except ValueError:
                    return {"ok": False, "error": "invalid_challenge"}
                state["pending"] = {**challenge, "id": secrets.token_hex(16), "issued_at": now,
                    "day": datetime.fromtimestamp(now).date().isoformat()}
                self.persist(uid, state)
                return {"ok": True, **self.public_challenge(state["pending"])}
            identifier = message.get("id")
            if isinstance(identifier, str) and identifier in state["receipts"]:
                receipt = state["receipts"][identifier]
                return {"ok": True, "id": identifier, **receipt["verdict"], "reward_seconds": 0,
                    "reward_pending": False, "already_completed": True}
            pending = state.get("pending")
            if not pending or identifier != pending["id"]:
                return {"ok": False, "error": "stale_challenge"}
            elapsed = now - pending["issued_at"]
            if elapsed > 1800 or elapsed < 0 or pending["day"] != datetime.fromtimestamp(now).date().isoformat():
                return {"ok": False, "error": "expired"}
            if elapsed < 1.5:
                return {"ok": False, "error": "too_fast"}
            verdict = self.verify(pending, message, elapsed)
            if not verdict.get("ok"):
                return verdict
            receipts = state["receipts"]
            # Keep recent verdicts for retries without recounting a completion.
            while len(receipts) >= 256:
                receipts.pop(next(iter(receipts)))
            receipt = {"id": identifier, "reward_seconds": 0, "verdict": verdict}
            state["pending"] = None
            receipts[identifier] = receipt
            self.persist(uid, state)
            return {**verdict, "id": identifier, "reward_seconds": 0,
                "reward_pending": False, "already_completed": False}

    def tick(self, now, elapsed):
        # Retire pending credits from older releases, including after reboot.
        for uid in self.managed_uids():
            self.account(uid)

    def save(self):
        pass
