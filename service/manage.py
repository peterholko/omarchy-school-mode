"""Install and manage the reviewed local controls service. Run via sudo."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE))
from omarchy_kids.core import paths, proto
from omarchy_kids.core.credentials import password_record, PASSWORD_PATH
from omarchy_kids.core.storage import locked, read_json, write_json

PREFIX = Path('/usr/lib/omarchy-kids-controls')
CONFIG = Path('/etc/omarchy-kids-controls')
STATE = Path('/var/lib/omarchy-kids-controls')
UNIT = Path('/etc/systemd/system/omarchy-kids-controls.service')
MARKER = CONFIG / 'installation.json'
VERSION = (SOURCE / 'VERSION').read_text().strip()
IDENTITY = 'peterholko/omarchy-kids-controls'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def ensure_directory(path, mode):
    if path.is_symlink():
        raise ValueError(f'refusing a symlink at {path}')
    path.mkdir(parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError(f'unexpected directory owner at {path}')
    path.chmod(mode)


def payload_files(source):
    result = {}
    for path in sorted(source.rglob('*')):
        if '.git' in path.parts or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError(f'symlinks are not allowed in the service payload: {path}')
        if path.is_file():
            result[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():
            raise ValueError(f'unsupported service file: {path}')
    return result


def verify_owned(path):
    info = path.lstat()
    if path.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError(f'installed path is not privately managed by root: {path}')


def wrappers():
    result = {}
    for role in ('time', 'school', 'grove'):
        name = 'omarchy-kids-controls-' + role + '-client'
        result[Path('/usr/bin') / name] = f'#!/bin/bash\nexec /usr/bin/python3 -I {PREFIX}/runtime.py {role} "$@"\n'
    result[Path('/usr/bin/omarchy-kids-controls')] = f'#!/bin/bash\nexec /usr/bin/python3 -I {PREFIX}/manage.py "$@"\n'
    return result


def installed():
    data = read_json(MARKER, {})
    if data and data.get('identity') != IDENTITY:
        raise ValueError('the existing service installation has an unknown owner')
    return data


def write_wrapper(path, text):
    paths.write_private(path, text)
    path.chmod(0o755)


def set_parent_password():
    if not sys.stdin.isatty():
        raise ValueError('run setup in a terminal to enter the parent password privately')
    print('Set the password used by these plugins. Login, sudo and disk passwords stay as they are.')
    password = getpass.getpass('New controls parent password: ')
    record = password_record(password)
    if password != getpass.getpass('Confirm parent password: '):
        raise ValueError('the parent passwords did not match')
    write_json(PASSWORD_PATH, record)


def check_account(name):
    account = pwd.getpwnam(name)
    if not 1000 <= account.pw_uid < 65534:
        raise ValueError('choose a regular local account')
    # Running both backends against one account would enforce two unrelated
    # budgets. Keep existing Kids installations out of this standalone path.
    for file in ('screen-time.json', 'school-mode.json'):
        legacy = Path('/etc/omarchy/parent') / file
        if name in read_json(legacy, {}).get('users', {}):
            raise ValueError('this account already has Omarchy Kids controls; disable those before enabling the standalone controls')
    return account


def config_path(module):
    return CONFIG / ('screen-time.json' if module == 'time' else 'school-mode.json')


def initialize_config():
    from omarchy_kids.screen_time import config as time_config
    from omarchy_kids.school_mode import config as school_config
    for module, config in (('time', time_config), ('school', school_config)):
        target = config_path(module)
        if not target.exists():
            write_json(target, config.sanitize({}))


def request(payload):
    return proto.request([Path('/run/omarchy-kids-controls/sock')], payload, timeout=15)


def enroll(module, user, enabled):
    result = request({'scope': module, 'cmd': 'users.set', 'user': user, 'enabled': enabled})
    if result.get('ok') is not True:
        raise ValueError(f'could not change {module} enrollment: {result.get("error", "unknown error")}')


def wait_for_service():
    import time
    for _ in range(30):
        try:
            if request({'cmd': 'ping'}).get('ok'):
                return
        except (OSError, proto.ProtocolError):
            pass
        time.sleep(0.1)
    raise ValueError('the service did not start; inspect journalctl -u omarchy-kids-controls')


def install(args):
    check_account(args.user)
    if not Path('/usr/share/omarchy/config/omarchy/shell.json').is_file():
        raise ValueError('install on Omarchy Quattro with its packaged shell')
    ensure_directory(CONFIG, 0o700)
    ensure_directory(STATE, 0o755)
    previous = installed()
    incoming = payload_files(SOURCE)
    owned = previous.get('payload', {})
    if PREFIX.exists() or PREFIX.is_symlink():
        if not previous or PREFIX.is_symlink():
            raise ValueError(f'unknown existing installation at {PREFIX}')
        if payload_files(PREFIX) != owned:
            raise ValueError('the installed service has local edits; preserve and review them before upgrading')
        for path in [PREFIX, *PREFIX.rglob('*')]:
            verify_owned(path)
    for path, text in wrappers().items():
        if (path.exists() or path.is_symlink()) and (not previous or path.is_symlink() or path.read_text() != text):
            raise ValueError(f'command collision at {path}')
        if path.exists():
            verify_owned(path)
    if (UNIT.exists() or UNIT.is_symlink()) and (not previous or UNIT.is_symlink() or UNIT.read_text() != previous.get('unit')):
        raise ValueError(f'service collision at {UNIT}')
    if UNIT.exists():
        verify_owned(UNIT)
    if previous and previous.get('version') != VERSION and not args.upgrade:
        raise ValueError('review the new service revision, then rerun with --upgrade; existing settings are retained')
    if previous and previous.get('version') == VERSION and owned != incoming:
        raise ValueError('two different service payloads claim the same version; use matching plugin releases')
    if not PASSWORD_PATH.exists():
        set_parent_password()
    initialize_config()
    if not previous or owned != incoming:
        stage = Path(tempfile.mkdtemp(prefix='.omarchy-kids-controls-', dir=PREFIX.parent))
        old = PREFIX.with_name('.omarchy-kids-controls-previous')
        try:
            for relative in incoming:
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SOURCE / relative, target)
                target.chmod(0o644)
            for directory in [stage, *[p for p in stage.rglob('*') if p.is_dir()]]:
                directory.chmod(0o755)
            if payload_files(stage) != incoming:
                raise ValueError('the source payload changed during installation; review it and retry')
            if old.exists():
                raise ValueError(f'a previous upgrade needs inspection at {old}')
            if PREFIX.exists():
                run('systemctl', 'stop', UNIT.name)
                PREFIX.rename(old)
            try:
                stage.rename(PREFIX)
            except OSError:
                if old.exists():
                    old.rename(PREFIX)
                raise
            if old.exists():
                shutil.rmtree(old)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    # Record ownership before creating wrappers/unit so an interrupted setup
    # can safely be retried without adopting unrelated files.
    unit = (SOURCE / UNIT.name).read_text()
    modules = sorted(set(previous.get('modules', [])) | {args.module})
    write_json(MARKER, {'identity': IDENTITY, 'version': VERSION, 'payload': incoming, 'unit': unit, 'modules': modules})
    for path, text in wrappers().items():
        write_wrapper(path, text)
    paths.write_private(UNIT, unit)
    UNIT.chmod(0o644)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', UNIT.name)
    wait_for_service()
    enroll(args.module, args.user, True)
    print(f'{args.module} controls enabled for {args.user}. The other module settings were retained.')
    print('Open the plugin’s parent settings to choose the schedule and limits.')


def restore_desktop(username):
    from omarchy_kids.core.session import _as_user
    result = _as_user(pwd.getpwnam(username).pw_uid,
        ['/usr/bin/python3', str(PREFIX / 'school-desktop.py'), 'restore'], timeout=20)
    if result is None or result.returncode:
        raise ValueError(f'could not restore {username}’s school desktop; run desktop.py restore in that session before removing the service')


def remove(module):
    marker = installed()
    if module not in marker.get('modules', []):
        print(f'{module} is not installed')
        return
    for user in list(read_json(config_path(module), {}).get('users', {})):
        enroll(module, user, False)
        if module == 'school':
            restore_desktop(user)
    marker['modules'].remove(module)
    if marker['modules']:
        write_json(MARKER, marker)
        print(f'{module} removed; the shared service remains for the other module.')
        return
    if payload_files(PREFIX) != marker['payload']:
        raise ValueError('the installed payload has local edits; removal stopped after disabling controls')
    for path, text in wrappers().items():
        if path.is_symlink() or path.read_text() != text:
            raise ValueError(f'command changed since installation: {path}')
    if UNIT.is_symlink() or UNIT.read_text() != marker['unit']:
        raise ValueError('the service unit changed since installation; removal stopped')
    run('systemctl', 'disable', '--now', UNIT.name)
    UNIT.unlink()
    for path in wrappers():
        path.unlink()
    shutil.rmtree(PREFIX)
    MARKER.unlink()
    run('systemctl', 'daemon-reload')
    print('Controls service removed. Password settings and history were retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    installer = sub.add_parser('install')
    installer.add_argument('--module', choices=['time', 'school'], required=True)
    installer.add_argument('--user', required=True)
    installer.add_argument('--upgrade', action='store_true')
    for action in ('enable', 'disable'):
        command = sub.add_parser(action)
        command.add_argument('module', choices=['time', 'school'])
        command.add_argument('--user', required=True)
    sub.add_parser('password')
    sub.add_parser('remove').add_argument('module', choices=['time', 'school'])
    args = parser.parse_args()
    if os.geteuid() != 0 or sys.platform != 'linux':
        parser.error('run this command with sudo on the Omarchy laptop')
    os.environ['PATH'] = '/usr/bin:/bin'
    ensure_directory(CONFIG, 0o700)
    with locked(CONFIG / '.setup.lock'):
        if args.action == 'install':
            install(args)
        elif args.action == 'password':
            set_parent_password()
        elif args.action == 'remove':
            remove(args.module)
        else:
            if args.module not in installed().get('modules', []):
                raise ValueError('install this module with its plugin setup command first')
            if args.action == 'enable':
                check_account(args.user)
            enroll(args.module, args.user, args.action == 'enable')
            if args.action == 'disable' and args.module == 'school':
                restore_desktop(args.user)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Setup stopped: {error}')
