"""Atomic, root-owned settings and public status for parent modules."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
from . import paths


def read_json(path, default=None):
    text = paths.read_regular(Path(path))
    if text is None:
        return default
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError(f"expected an object in {path}")
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    paths.write_private(path, json.dumps(value, indent=2) + "\n")


@contextlib.contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def school_config_path(layout):
    return layout.config_path.with_name("school-mode.json")


def public_status(layout, username, feature, payload):
    target = layout.status_path(username)
    if feature != "time":
        target = target.parent.parent / feature / "status.json"
    if layout.mode == "system":
        paths.private_dir(paths.PARENT_STATE_DIR, mode=0o755, scrub=False)
        paths.private_dir(target.parent.parent, mode=0o755, scrub=False)
    paths.private_dir(target.parent, mode=0o755, scrub=False)
    # Stage with the private writer's no-symlink/owner checks, then expose only
    # the deliberately public payload. The directory is not child-writable.
    paths.write_private(target, json.dumps(payload) + "\n")
    os.chmod(target, 0o644)
