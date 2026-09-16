"""Exercise only temporary lock views; never install or activate a lock."""
from functools import partial
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'service'))
from omarchy_kids.school_mode import lock_notice_setup as notice

VIEW = '''import QtQuick
Item {
  id: root
  property bool inputEnabled: true
  property bool loadBackground: true
  signal submitPassword(string password)
  Rectangle {
    anchors.fill: parent
    Rectangle { id: inputField; anchors.centerIn: parent }
  }
}
'''


class LockNoticeSetup(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.base = self.root / 'omarchy'
        self.target = self.base / notice.RELATIVE_VIEW
        self.target.parent.mkdir(parents=True)
        self.target.write_text(VIEW)
        self.receipt = self.root / 'receipt.json'
        self.component = self.root / 'LockNotice.qml'
        # Model the filesystem root inside a temporary user-owned tree.
        bounded_read = partial(notice.read_owned, trusted_root=self.root)
        context = patch.object(notice, 'read_owned', bounded_read)
        context.start()
        self.addCleanup(context.stop)

    def plan(self, base=None):
        return notice.plan(base or self.base, self.receipt, os.getuid(), self.component)

    def install(self):
        notice.install(self.plan(), self.receipt, os.getuid())

    def remove(self):
        notice.remove(self.receipt, os.getuid())

    def test_install_repeat_and_remove_preserve_every_original_byte(self):
        self.install()
        installed = self.target.read_text()
        self.assertEqual(installed.count(notice.BEGIN), 1)
        self.assertEqual(installed.replace(notice.snippet(self.component), ''), VIEW)
        self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o644)
        self.install()
        self.assertEqual(self.target.read_text(), installed)
        self.remove()
        self.assertEqual(self.target.read_text(), VIEW)
        self.assertFalse(self.receipt.exists())
        self.remove()

    def test_reapply_after_package_update_and_remove_preserve_upstream_changes(self):
        self.install()
        updated = VIEW.replace('property bool inputEnabled:', '// upstream change\n  property bool inputEnabled:')
        self.target.write_text(updated)
        self.install()
        self.target.write_text(self.target.read_text().replace('signal submitPassword', '// another update\n  signal submitPassword'))
        self.remove()
        self.assertEqual(self.target.read_text(), updated.replace('signal submitPassword', '// another update\n  signal submitPassword'))
        self.install()
        self.target.write_text(updated)
        self.remove()
        self.assertEqual(self.target.read_text(), updated)

    def test_interrupted_install_can_resume_and_cannot_overwrite_concurrent_update(self):
        prepared = self.plan()
        notice.write_json(self.receipt, {key: prepared[key] for key in ('version', 'target', 'block')})
        self.install()
        prepared = self.plan()
        self.target.write_text(VIEW + '// changed concurrently\n')
        with self.assertRaisesRegex(ValueError, 'changed during setup'):
            notice.install(prepared, self.receipt, os.getuid())
        self.assertEqual(self.target.read_text(), VIEW + '// changed concurrently\n')

    def test_edited_notice_collisions_and_incompatible_host_fail_before_writing(self):
        for text in [VIEW + notice.snippet(self.component), VIEW.replace('id: inputField', 'id: renamedField')]:
            self.target.write_text(text)
            with self.assertRaises(ValueError):
                self.install()
            self.assertFalse(self.receipt.exists())
            self.assertEqual(self.target.read_text(), text)
        self.target.write_text(VIEW)
        self.install()
        edited = self.target.read_text().replace('    active:', '    visible:')
        self.target.write_text(edited)
        for action in (self.install, self.remove):
            with self.assertRaisesRegex(ValueError, 'was edited'):
                action()
            self.assertEqual(self.target.read_text(), edited)

    def test_user_writable_files_directories_and_symlinks_are_rejected(self):
        for path in [self.target, self.target.parent]:
            original_mode = path.stat().st_mode & 0o777
            path.chmod(0o777)
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                self.install()
            path.chmod(original_mode)
        backup = self.target.with_suffix('.original')
        self.target.rename(backup)
        self.target.symlink_to(backup)
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.install()
        self.target.unlink()
        backup.rename(self.target)
        linked = self.root / 'linked'
        linked.symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.plan(linked)
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            notice.read_owned(self.target, os.getuid() + 1)

    def test_explicit_path_survives_sudo_and_receipt_supports_later_repairs(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'omarchy-path'):
                notice.plan(receipt=self.receipt, owner=os.getuid())
            self.install()
            prepared = notice.plan(receipt=self.receipt, owner=os.getuid(), component=self.component)
            self.assertEqual(prepared['target'], str(self.target))
            with self.assertRaisesRegex(ValueError, 'path changed'):
                self.plan(self.root / 'another-install')
            with self.assertRaisesRegex(ValueError, 'absolute'):
                self.plan(Path('relative-omarchy'))

    def test_unknown_receipts_are_not_adopted_or_removed(self):
        for value in [{}, [], {'version': 1, 'block': '', 'target': str(self.target)},
                      {'version': 1, 'block': notice.snippet(self.component), 'target': '/unrelated-file'}]:
            original = json.dumps(value)
            self.receipt.write_text(original)
            for action in (self.install, self.remove):
                with self.assertRaisesRegex(ValueError, 'unknown'):
                    action()
                self.assertEqual(self.receipt.read_text(), original)
                self.assertEqual(self.target.read_text(), VIEW)


if __name__ == '__main__':
    unittest.main()
