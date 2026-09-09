"""Consented, reversible desktop effects, run only as the desktop user.

enable grants permission to temporarily hide the stock launcher, quiet
notifications, park windows and redirect standard app shortcuts. disable
revokes that permission and restores the recorded state. No root execution.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile

SOURCE = Path(__file__).resolve().parent
STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'omarchy-community-school-mode'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'omarchy/shell.json'
JOURNAL = STATE / 'desktop.json'
CONSENT = STATE / 'consent.json'


def read(path, default=None):
    if not path.exists():
        return default
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'expected a regular file at {path}')
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f'refusing to replace a symlink at {path}')
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ValueError(f'{Path(args[0]).name} could not complete {args[1] if len(args) > 1 else ""}')
    return result.stdout.strip()


def shell_config():
    existing = read(CONFIG)
    if existing is not None:
        if not isinstance(existing, dict) or not isinstance(existing.get('disabledPlugins', []), list):
            raise ValueError('shell.json has an unsupported shape; it has not been changed')
        return existing
    return read(Path(os.environ['OMARCHY_PATH']) / 'config/omarchy/shell.json')


def menu(disabled):
    current = shell_config()
    values = current.get('disabledPlugins', [])
    revised = list(dict.fromkeys([*values, 'omarchy.menu'])) if disabled else [v for v in values if v != 'omarchy.menu']
    if revised != values:
        current['disabledPlugins'] = revised
        write(CONFIG, current)


def enter(journal):
    instance = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
    if not journal:
        dnd = command('omarchy-shell', 'notifications', 'dndState')
        if dnd not in ('on', 'off'):
            raise ValueError('notification service is not ready')
        config = shell_config()
        journal = {'version': 1, 'menuWasDisabled': 'omarchy.menu' in config.get('disabledPlugins', []),
                   'dnd': dnd, 'effectsApplied': False, 'instance': instance}
        # Persist recovery before changing anything. Keep a one-time full
        # backup for inspection; restoration changes only our own setting.
        if CONFIG.exists() and not (STATE / 'shell.before-school.json').exists():
            write(STATE / 'shell.before-school.json', config)
        write(JOURNAL, journal)
    if instance and instance != journal.get('instance'):
        journal['effectsApplied'] = False
        journal['instance'] = instance
        write(JOURNAL, journal)
    if not journal.get('effectsApplied'):
        command('/bin/bash', str(SOURCE / 'window-session'), 'enter')
        command('/bin/bash', str(SOURCE / 'shortcut-policy'), 'enter')
        menu(True)
        command('omarchy-shell', 'notifications', 'setDnd', 'on')
        journal['effectsApplied'] = True
        write(JOURNAL, journal)
    command('/bin/bash', str(SOURCE / 'window-session'), 'guard')


def restore(journal):
    if not journal:
        return
    # Retain the recovery journal on any failure so the next attempt can
    # finish. Restoring one flag never overwrites other desktop settings.
    if not journal.get('menuWasDisabled'):
        menu(False)
    errors = []
    for args in [('/bin/bash', str(SOURCE / 'window-session'), 'exit'),
                 ('/bin/bash', str(SOURCE / 'shortcut-policy'), 'exit'),
                 ('omarchy-shell', 'notifications', 'setDnd', journal['dnd'])]:
        try:
            command(*args)
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            errors.append(str(error))
    if errors:
        raise ValueError('; '.join(errors))
    JOURNAL.unlink()


def synchronize():
    journal = read(JOURNAL, {})
    if not read(CONSENT, {}).get('enabled'):
        restore(journal)
        return
    username = pwd.getpwuid(os.getuid()).pw_name
    status = read(Path('/var/lib/omarchy-kids-controls/status') / username / 'school-mode/status.json')
    if status is None:
        # Missing status must not accidentally release an active policy.
        if journal:
            raise ValueError('waiting for the school controls service')
        return
    if status.get('schemaVersion') != 1 or not isinstance(status.get('enabled'), bool):
        raise ValueError('waiting for valid school status')
    if status.get('enabled') and status.get('mode') not in ('school', 'free'):
        raise ValueError('waiting for valid school mode')
    if status.get('enabled') and status.get('mode') == 'school':
        enter(journal)
    else:
        restore(journal)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['enable', 'disable', 'sync', 'restore'])
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('run this command as the desktop user, without sudo')
    if STATE.is_symlink():
        raise ValueError('refusing a symlink state directory')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if STATE.stat().st_uid != os.getuid():
        raise ValueError('state directory belongs to another account')
    STATE.chmod(0o700)
    fd = os.open(STATE / 'desktop.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == 'enable':
            write(CONSENT, {'enabled': True})
            synchronize()
        elif args.action == 'disable':
            write(CONSENT, {'enabled': False})
            restore(read(JOURNAL, {}))
        elif args.action == 'restore':
            restore(read(JOURNAL, {}))
        else:
            synchronize()
    print(json.dumps({'ok': True}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        raise SystemExit(1)
