"""Reversible, per-service PAM wrappers; never modify global login policy."""
import json
from pathlib import Path
import stat
from omarchy_kids.core.paths import write_public
from omarchy_kids.core.storage import write_json

PAM_DIR = Path('/etc/pam.d')
RECEIPT = Path('/etc/omarchy-kids-controls/school-pam.json')
HELPER = '/usr/bin/omarchy-kids-controls-school-pam'
SERVICES = ('omarchy-lock-password', 'omarchy-lock-fingerprint', 'hyprlock', 'sddm', 'sddm-autologin')
STAMP = '# Managed by omarchy-kids-controls School / Free Time\n'


def original_name(name):
    return 'omarchy-school-original-' + name


def wrapper(name):
    original = original_name(name)
    if name in ('omarchy-lock-fingerprint', 'sddm-autologin'):
        auth = f'auth requisite pam_exec.so quiet {HELPER} gate\n'
    else:
        auth = (f'auth [success=1 default=ignore] pam_exec.so quiet {HELPER} gate\n'
                f'auth [success=done default=die] pam_exec.so quiet expose_authtok {HELPER} unlock\n')
    # A substack preserves original success/failure jumps inside the original
    # stack. Its success cannot skip the final gate if time expires mid-auth.
    return ('#%PAM-1.0\n' + STAMP + auth
            + f'auth substack {original}\n'
            + f'auth requisite pam_exec.so quiet {HELPER} gate\n'
            + f'account requisite pam_exec.so quiet {HELPER} gate\n'
            + f'account substack {original}\n'
            + f'password substack {original}\n'
            + f'session substack {original}\n')


def read_owned(path, owner=0):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
        raise ValueError(f'unsafe PAM file: {path}')
    return path.read_text()


def plan(pam_dir=PAM_DIR, receipt=RECEIPT, owner=0):
    previous = json.loads(read_owned(receipt, owner)) if receipt.exists() else {}
    if not (pam_dir / 'omarchy-lock-password').is_file():
        raise ValueError('Omarchy password lock authentication is missing; configure it before School Mode setup')
    entries = dict(previous.get('services', {}))
    if set(entries) - set(SERVICES):
        raise ValueError('unknown service in School Mode PAM receipt')
    for name in SERVICES:
        path = pam_dir / name
        if not path.exists() and not path.is_symlink():
            continue
        current = read_owned(path, owner)
        original = pam_dir / original_name(name)
        if name in entries:
            entry = entries[name]
            backup_ok = read_owned(original, owner) == entry['original'] if original.exists() else current == entry['original']
            if current not in (wrapper(name), entry['original']) or not backup_ok:
                raise ValueError(f'{path} changed after School Mode setup; preserve and review its changes before reinstalling')
        else:
            if original.exists() or original.is_symlink() or STAMP in current:
                raise ValueError(f'PAM backup collision at {original}')
            entries[name] = {'original': current, 'wrapper': wrapper(name)}
    return {'version': 1, 'services': entries}


def install(prepared, pam_dir=PAM_DIR, receipt=RECEIPT):
    # Write a recovery receipt and originals before replacing any entry point.
    write_json(receipt, prepared)
    for name, entry in prepared['services'].items():
        original = pam_dir / original_name(name)
        if not original.exists():
            write_public(original, entry['original'])
        write_public(pam_dir / name, entry['wrapper'])


def ready(pam_dir=PAM_DIR, receipt=RECEIPT, owner=0):
    try:
        data = json.loads(read_owned(receipt, owner))
        entries = data['services']
        if 'omarchy-lock-password' not in entries:
            return False
        for name in SERVICES:
            if (pam_dir / name).exists() and name not in entries:
                return False
        for name, entry in entries.items():
            if name not in SERVICES or read_owned(pam_dir / name, owner) != wrapper(name):
                return False
            if read_owned(pam_dir / original_name(name), owner) != entry['original']:
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def remove(pam_dir=PAM_DIR, receipt=RECEIPT, owner=0):
    if not receipt.exists():
        return
    data = json.loads(read_owned(receipt, owner))
    if set(data['services']) - set(SERVICES):
        raise ValueError('unknown service in School Mode PAM receipt')
    for name, entry in data['services'].items():
        current = read_owned(pam_dir / name, owner)
        original = pam_dir / original_name(name)
        # An interrupted removal may already have restored an entry point or
        # removed its backup. Never overwrite an administrator's new edits.
        backup_ok = read_owned(original, owner) == entry['original'] if original.exists() or original.is_symlink() else current == entry['original']
        if current not in (wrapper(name), entry['original']) or not backup_ok:
            raise ValueError(f'PAM configuration changed after setup: {name}; preserve and review it before removal')
    for name, entry in data['services'].items():
        write_public(pam_dir / name, entry['original'])
    for name in data['services']:
        (pam_dir / original_name(name)).unlink(missing_ok=True)
    receipt.unlink()
