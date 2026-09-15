"""PAM's fixed local gate; passwords only travel through stdin and the socket."""
import json
import os
from pathlib import Path
import pwd
import stat
import sys
from omarchy_kids.core import proto

SOCKET = Path('/run/omarchy-kids-controls/sock')
STATUS = Path('/var/lib/omarchy-kids-controls/status')


def enrolled(username, status_root=STATUS):
    path = status_root / username / 'school-mode/status.json'
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        with os.fdopen(fd) as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                return True
            return json.load(handle).get('enabled') is not False
    except (OSError, ValueError, TypeError, AttributeError):
        return True


def authenticate(action, request, password=''):
    """Gate every attempt against live policy, including an already locked screen."""
    if action == 'gate':
        result = request({'scope': 'school', 'cmd': 'status'})
        return (result.get('ok') is True and result.get('free_time_expired') is False) or result.get('error') == 'not_managed'
    result = request({'scope': 'school', 'cmd': 'free-time.unlock', 'password': password})
    return result.get('ok') is True and result.get('mode') == 'school'


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('gate', 'unlock'):
        return 1
    action = sys.argv[1]
    if os.environ.get('PAM_TYPE') not in ('auth', 'account') or (action == 'unlock' and os.environ.get('PAM_TYPE') != 'auth'):
        return 1
    try:
        account = pwd.getpwnam(os.environ.get('PAM_USER', ''))
        caller = os.getuid()
        if caller not in (0, account.pw_uid):
            return 1
        if action == 'gate' and (account.pw_uid == 0 or not enrolled(account.pw_name)):
            return 0
        if account.pw_uid == 0:
            return 1
        # PAM may run as root (the greeter). Authenticate as the target user
        # so the service never treats a typed password as a root override.
        if os.geteuid() == 0:
            os.setgroups([])
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
        if os.getuid() != account.pw_uid or os.geteuid() != account.pw_uid:
            return 1
        password = ''
        if action == 'unlock':
            token = sys.stdin.buffer.read(1025).rstrip(b'\x00')
            if not 1 <= len(token) <= 1024:
                return 1
            password = token.decode('utf-8')
        request = lambda payload: proto.request([SOCKET], payload, timeout=15)
        return 0 if authenticate(action, request, password) else 1
    except (OSError, ValueError, KeyError, proto.ProtocolError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
