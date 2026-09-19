"""Consented, reversible desktop effects, run only as the desktop user.

enable applies the approved launcher and shortcuts in School and Free Time.
School additionally quiets notifications and parks windows. disable restores
the recorded desktop state. No root execution.
"""
import argparse
import fcntl
import hashlib
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


def shortcuts_ready(mode):
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime:
        return False
    marker = Path(runtime) / 'omarchy-community-school-mode/shortcut-policy.active'
    if marker.is_symlink() or not marker.is_file():
        return False
    lines = marker.read_text().splitlines()
    if 'version=4' not in lines or f'mode={mode}' not in lines:
        return False
    # A compositor reload discards the live bindings without removing files
    # in XDG_RUNTIME_DIR. Inspect the live layer as well as its receipt. Use
    # text output: some supported Hyprland versions emit invalid binds JSON.
    descriptions = {line.strip().removeprefix('description: ')
                    for line in command('hyprctl', 'binds').splitlines()
                    if line.strip().startswith('description: ')}
    return {'School / Free Time: Menu', 'School / Free Time: Apps',
            'School / Free Time: Capture', 'School / Free Time: Screenrecording',
            'School / Free Time: Keybindings'} <= descriptions


def enter(journal, mode, effects=True):
    instance = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
    if not journal:
        config = shell_config()
        journal = {'version': 2, 'menuWasDisabled': 'omarchy.menu' in config.get('disabledPlugins', []),
                   'dnd': 'off', 'dndPending': True, 'schoolActive': False,
                   'schoolEffectsApplied': False, 'appliedMode': '', 'instance': instance}
        # Persist recovery before changing anything. Keep a one-time full
        # backup for inspection; restoration changes only our own setting.
        if CONFIG.exists() and not (STATE / 'shell.before-school.json').exists():
            write(STATE / 'shell.before-school.json', config)
        write(JOURNAL, journal)
    elif journal.get('version') == 1:
        # A v1 journal was only created while entering school. Preserve its
        # original recovery values, including partially applied effects.
        journal['version'] = 2
        journal['schoolActive'] = True
        journal['appliedMode'] = 'school' if journal.get('effectsApplied') else ''
        write(JOURNAL, journal)
    # Earlier journals used appliedMode for both bindings and school effects.
    # Keep those receipts separate so one failed effect cannot block the menu.
    journal.setdefault('schoolEffectsApplied',
                       journal.get('schoolActive', False) and journal.get('appliedMode') == 'school')
    if instance and instance != journal.get('instance'):
        journal['appliedMode'] = ''
        journal['schoolEffectsApplied'] = False
        journal['instance'] = instance
        write(JOURNAL, journal)

    # Free Time is still a child's desktop. Never restore the unrestricted
    # launcher as an intermediate step when changing modes.
    menu(True)

    shortcut_revision = hashlib.sha256((SOURCE / 'shortcut-policy').read_bytes()).hexdigest()
    if (journal.get('appliedMode') != mode or journal.get('shortcutRevision') != shortcut_revision
            or not shortcuts_ready(mode)):
        command('/bin/bash', str(SOURCE / 'shortcut-policy'), 'enter', mode)
        journal['appliedMode'] = mode
        journal['shortcutRevision'] = shortcut_revision
        write(JOURNAL, journal)

    # During startup, protect the launcher even while the policy service is
    # unavailable. Wait for authoritative status before moving any windows.
    if not effects:
        return
    if journal.get('dndPending') or (mode == 'school' and not journal.get('schoolActive')):
        dnd = command('omarchy-shell', 'notifications', 'dndState')
        if dnd not in ('on', 'off'):
            raise ValueError('notification service is not ready')
        journal['dnd'] = dnd
        journal['dndPending'] = False
        write(JOURNAL, journal)
    if mode == 'school':
        if not journal.get('schoolActive'):
            journal['schoolActive'] = True
            journal['schoolEffectsApplied'] = False
            write(JOURNAL, journal)
        if not journal.get('schoolEffectsApplied'):
            command('/bin/bash', str(SOURCE / 'window-session'), 'enter')
            command('omarchy-shell', 'notifications', 'setDnd', 'on')
            journal['schoolEffectsApplied'] = True
            write(JOURNAL, journal)
    elif journal.get('schoolActive'):
        journal['schoolEffectsApplied'] = False
        write(JOURNAL, journal)
        command('/bin/bash', str(SOURCE / 'window-session'), 'exit')
        command('omarchy-shell', 'notifications', 'setDnd', journal['dnd'])
        journal['schoolActive'] = False
        write(JOURNAL, journal)
    if mode == 'school':
        command('/bin/bash', str(SOURCE / 'window-session'), 'guard')


def restore(journal):
    if not journal:
        return
    # Retain the recovery journal on any failure so the next attempt can
    # finish. Restoring one flag never overwrites other desktop settings.
    if not journal.get('menuWasDisabled'):
        menu(False)
    errors = []
    actions = [('/bin/bash', str(SOURCE / 'window-session'), 'exit'),
               ('/bin/bash', str(SOURCE / 'shortcut-policy'), 'exit')]
    if journal.get('schoolActive', journal.get('version') == 1):
        actions.append(('omarchy-shell', 'notifications', 'setDnd', journal['dnd']))
    for args in actions:
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
    try:
        status = read(Path('/var/lib/omarchy-kids-controls/status') / username / 'school-mode/status.json')
    except (ValueError, OSError):
        status = None
    valid = (isinstance(status, dict) and status.get('schemaVersion') == 1
             and isinstance(status.get('enabled'), bool)
             and (not status['enabled'] or status.get('mode') in ('school', 'free')))
    if not valid:
        # A reboot loses runtime bindings, so merely keeping yesterday's
        # journal is insufficient. Reapply the restrictive startup shortcuts;
        # the menu shows no apps until it has valid status. Do not park windows
        # or change notifications until the service confirms the actual mode.
        enter(journal, 'school', effects=False)
        raise ValueError('waiting for valid school status from the controls service')
    if status.get('enabled'):
        enter(journal, status['mode'])
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
