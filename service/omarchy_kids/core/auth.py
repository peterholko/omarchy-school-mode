"""OS parent authentication shared by all privileged feature actions."""
import math
import os
import subprocess
import threading
import time
from . import session

PASSWORD_LOCKOUT = [0, 0, 1, 5, 15, 60, 300]

def parent_password_ok(username, password):
    """Check the separate plugin password; OS authentication is unchanged."""
    if os.geteuid() != 0 or not username or not password:
        return False
    from .credentials import verify_password
    return verify_password(password)

class ParentAuth:
    def __init__(self, verifier=None, monotonic=time.monotonic):
        self.verifier = verifier or parent_password_ok
        self.monotonic = monotonic
        self.failures = {}
        self.busy = set()
        self.lock = threading.Lock()

    def check(self, uid, message, demo=False):
        if uid == 0:
            return None
        password = str(message.get("password", message.get("pin", "")))
        with self.lock:
            count, until = self.failures.get(uid, (0, 0))
            now = self.monotonic()
            if uid in self.busy:
                return {"ok": False, "error": "password_checking"}
            if now < until:
                return {"ok": False, "error": "password_locked_out", "retry_in_seconds": math.ceil(until - now)}
            self.busy.add(uid)
        try:
            accepted = bool(password) and self.verifier(session.username_for(uid), password)
        except (OSError, subprocess.SubprocessError):
            accepted = False
        with self.lock:
            self.busy.discard(uid)
            if accepted:
                self.failures.pop(uid, None)
                return None
            count += 1
            self.failures[uid] = (count, self.monotonic() + PASSWORD_LOCKOUT[min(count, len(PASSWORD_LOCKOUT) - 1)])
        return {"ok": False, "error": "bad_password"}
