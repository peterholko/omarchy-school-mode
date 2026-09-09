"""The controls password is separate from login, root, sudo and disk keys."""
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import stat

PASSWORD_PATH = Path('/etc/omarchy-kids-controls/password.json')


def password_record(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 1024:
        raise ValueError('use a parent password between 8 and 1024 characters')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1,
                            maxmem=64 * 1024 * 1024, dklen=32)
    return {'version': 1, 'algorithm': 'scrypt', 'salt': salt.hex(), 'digest': digest.hex()}


def matches(password, record):
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        return False
    if record.get('version') != 1 or record.get('algorithm') != 'scrypt':
        return False
    try:
        salt = bytes.fromhex(record['salt'])
        expected = bytes.fromhex(record['digest'])
        if len(salt) != 16 or len(expected) != 32:
            return False
        actual = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1,
                                maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(actual, expected)
    except (ValueError, KeyError, TypeError):
        return False


def verify_password(password, path=PASSWORD_PATH):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            return False
        return matches(password, json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        return False
