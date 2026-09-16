"""Install a reversible display-only notice in Omarchy's native lock view.

The root-owned component reads public expiry status and has no authentication
API. Do not alter the lock service, its password input, or any PAM rules here.
"""
import json
import os
from pathlib import Path
import re
import stat

from omarchy_kids.core.paths import write_public
from omarchy_kids.core.storage import write_json

RECEIPT = Path('/etc/omarchy-kids-controls/school-lock-notice.json')
COMPONENT = Path('/usr/lib/omarchy-kids-controls/lock-notice/LockNotice.qml')
RELATIVE_VIEW = Path('shell/plugins/lock/LockView.qml')
BEGIN = '  // BEGIN School Mode parent-unlock notice\n'
END = '  // END School Mode parent-unlock notice\n'


def read_owned(path, owner=0, *, trusted_root=Path('/')):
    # Reject symlinked parents as well as a replaced destination. This code is
    # installed into the lock process, so it must remain administrator-owned.
    path.relative_to(trusted_root)
    for entry in [path, *path.parents]:
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
            raise ValueError(f'unsafe lock notice path: {entry}')
        if entry == trusted_root:
            break
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f'expected a regular lock view: {path}')
    return path.read_text()


def snippet(component=COMPONENT):
    return (BEGIN + '  Loader {\n'
            '    id: schoolModeLockNotice\n'
            '    parent: inputField.parent\n'
            '    active: root.inputEnabled && root.loadBackground\n'
            '    x: inputField.x + (inputField.width - width) / 2\n'
            '    y: inputField.y + inputField.height + Style.space(16)\n'
            '    width: Math.max(0, Math.min(parent.width - Style.space(32), Style.space(440)))\n'
            '    height: item ? item.implicitHeight : 0\n'
            f'    source: active ? {json.dumps(component.as_uri())} : ""\n'
            '  }\n' + END)


def without_notice(text, block):
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.count(block) != 1:
        raise ValueError('the School Mode lock notice was edited; preserve and review the changes')
    return text.replace(block, '', 1)


def add_notice(text, block):
    required = ('id: root', 'id: inputField', 'property bool inputEnabled:', 'property bool loadBackground:')
    if not all(part in text for part in required) or not re.search(r'\n}\s*\Z', text):
        raise ValueError('this Omarchy lock view is not supported by the parent-password notice')
    if BEGIN in text or END in text or 'schoolModeLockNotice' in text:
        raise ValueError('an unrecognized School Mode lock notice already exists')
    closing = text.rfind('\n}')
    return text[:closing + 1] + block + text[closing + 1:]


def read_receipt(receipt, owner):
    data = json.loads(read_owned(receipt, owner))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('block'), str) or not isinstance(data.get('target'), str):
        raise ValueError('unknown School Mode lock notice receipt')
    target = Path(data['target'])
    if (not target.is_absolute() or '..' in target.parts or not str(target).endswith('/' + str(RELATIVE_VIEW))
            or not data['block'].startswith(BEGIN) or not data['block'].endswith(END)):
        raise ValueError('unknown School Mode lock notice receipt')
    return data


def plan(omarchy_path=None, receipt=RECEIPT, owner=0, component=COMPONENT):
    previous = read_receipt(receipt, owner) if receipt.exists() or receipt.is_symlink() else None
    configured = omarchy_path or os.environ.get('OMARCHY_PATH')
    if configured:
        base = Path(configured)
        if not base.is_absolute() or '..' in base.parts:
            raise ValueError('--omarchy-path must be an absolute Omarchy installation path')
        target = base / RELATIVE_VIEW
    elif previous:
        target = Path(previous['target'])
    else:
        raise ValueError('pass --omarchy-path "$OMARCHY_PATH" from the Omarchy desktop terminal to install the lock notice')
    if previous and str(target) != previous.get('target'):
        raise ValueError('the Omarchy path changed; remove the previous lock notice before installing it at the new path')
    current = read_owned(target, owner)
    if previous and BEGIN in current:
        original = without_notice(current, previous['block'])
    else:
        # A normal Omarchy package update can replace the view. Add the notice
        # to that new version; never restore an old full-file backup over it.
        original = current
    block = snippet(component)
    updated = add_notice(original, block)
    return {'version': 1, 'target': str(target), 'block': block, 'observed': current, 'updated': updated}


def install(prepared, receipt=RECEIPT, owner=0):
    target = Path(prepared['target'])
    if read_owned(target, owner) != prepared['observed']:
        raise ValueError('the Omarchy lock view changed during setup; retry after the update completes')
    # Record the exact owned block before publishing so interrupted setup can
    # resume. The receipt deliberately does not authorize replacing the rest.
    write_json(receipt, {key: prepared[key] for key in ('version', 'target', 'block')})
    if prepared['observed'] != prepared['updated']:
        write_public(target, prepared['updated'])


def remove(receipt=RECEIPT, owner=0):
    if not receipt.exists() and not receipt.is_symlink():
        return
    previous = read_receipt(receipt, owner)
    target = Path(previous['target'])
    if target.exists() or target.is_symlink():
        current = read_owned(target, owner)
        if BEGIN in current or END in current:
            write_public(target, without_notice(current, previous['block']))
    receipt.unlink()
