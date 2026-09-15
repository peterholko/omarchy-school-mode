"""Temporary-file installation and PAM process-boundary regressions.

These exercise our helper and installer; they do not emulate Linux PAM itself.
"""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'service'))
from omarchy_kids.school_mode import pam_helper, pam_setup


class Installation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pam = self.root / 'pam.d'
        self.pam.mkdir()
        self.receipt = self.root / 'school-pam.json'
        self.originals = {
            'omarchy-lock-password': '#%PAM-1.0\nauth include system-auth\n',
            'omarchy-lock-fingerprint': 'auth sufficient pam_fprintd.so\n',
            'hyprlock': 'auth include system-auth\n',
            'sddm': 'auth substack system-auth\naccount include system-auth\nsession include system-auth\n',
            'sddm-autologin': 'auth required pam_permit.so\n',
            'sudo': 'auth required pam_unix.so\n',
            'system-auth': 'auth sufficient pam_unix.so\n',
        }
        for name, content in self.originals.items():
            (self.pam / name).write_text(content)
        self.owner = os.getuid()

    def install(self):
        plan = pam_setup.plan(self.pam, self.receipt, self.owner)
        pam_setup.install(plan, self.pam, self.receipt)

    def ready(self):
        return pam_setup.ready(self.pam, self.receipt, self.owner)

    def remove(self):
        pam_setup.remove(self.pam, self.receipt, self.owner)

    def test_install_reinstall_and_remove_preserve_exact_originals_and_global_policy(self):
        self.assertFalse(self.ready())
        self.install()
        self.assertTrue(self.ready())
        self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o600)
        for name in ('sudo', 'system-auth'):
            self.assertEqual((self.pam / name).read_text(), self.originals[name])
        for name in pam_setup.SERVICES:
            self.assertEqual((self.pam / pam_setup.original_name(name)).read_text(), self.originals[name])
            self.assertEqual((self.pam / name).stat().st_mode & 0o777, 0o644)
        self.install()
        self.remove()
        self.remove()
        self.assertFalse(self.receipt.exists())
        self.assertEqual({p.name: p.read_text() for p in self.pam.iterdir()}, self.originals)

    def test_collisions_symlinks_and_local_edits_stop_before_mutation(self):
        backup = self.pam / pam_setup.original_name('omarchy-lock-password')
        backup.write_text('unrelated administrator file')
        with self.assertRaisesRegex(ValueError, 'collision'):
            self.install()
        self.assertFalse(self.receipt.exists())
        backup.unlink()
        password = self.pam / 'omarchy-lock-password'
        password.unlink()
        password.symlink_to(self.pam / 'system-auth')
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.install()
        password.unlink()
        password.write_text(self.originals[password.name])
        self.install()
        password.write_text('new local PAM rules')
        self.assertFalse(self.ready())
        for action in (self.install, self.remove):
            with self.assertRaisesRegex(ValueError, 'changed'):
                action()
        self.assertEqual(password.read_text(), 'new local PAM rules')

    def test_interrupted_install_and_removal_can_resume(self):
        prepared = pam_setup.plan(self.pam, self.receipt, self.owner)
        pam_setup.write_json(self.receipt, prepared)
        first = next(iter(prepared['services']))
        pam_setup.write_public(self.pam / pam_setup.original_name(first), self.originals[first])
        self.install()
        self.assertTrue(self.ready())
        pam_setup.write_public(self.pam / first, self.originals[first])
        (self.pam / pam_setup.original_name(first)).unlink()
        self.remove()
        self.assertEqual({p.name: p.read_text() for p in self.pam.iterdir()}, self.originals)

    def test_new_authentication_entry_point_requires_setup_before_another_grant(self):
        (self.pam / 'hyprlock').unlink()
        self.install()
        self.assertTrue(self.ready())
        (self.pam / 'hyprlock').write_text(self.originals['hyprlock'])
        self.assertFalse(self.ready())
        self.install()
        self.assertTrue(self.ready())


class Helper(unittest.TestCase):
    def invoke(self, action, result=None, password=b'', caller=0, enrolled=True, pam_type='auth', user='linnea'):
        uid = 0 if user == 'root' else 1000
        ids = {'real': caller, 'effective': caller}
        events = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'argv', ['helper', action]))
            stack.enter_context(patch.dict(os.environ, {'PAM_USER': user, 'PAM_TYPE': pam_type,
                'SCREEN_TIME_ROOT': '/untrusted', 'OMARCHY_PATH': '/untrusted'}))
            stack.enter_context(patch.object(pam_helper.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=uid, pw_gid=1000, pw_name=user)))
            stack.enter_context(patch.object(pam_helper, 'enrolled', return_value=enrolled))
            stack.enter_context(patch.object(os, 'getuid', side_effect=lambda: ids['real']))
            stack.enter_context(patch.object(os, 'geteuid', side_effect=lambda: ids['effective']))
            stack.enter_context(patch.object(os, 'setgroups', side_effect=lambda groups: events.append(('groups', groups))))
            stack.enter_context(patch.object(os, 'setgid', side_effect=lambda gid: events.append(('gid', gid))))
            def drop_uid(value):
                events.append(('uid', value))
                ids.update(real=value, effective=value)
            stack.enter_context(patch.object(os, 'setuid', side_effect=drop_uid))
            stack.enter_context(patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(password))))
            def request(sockets, payload, **kwargs):
                self.assertEqual(ids, {'real': 1000, 'effective': 1000}, 'root must not authenticate typed passwords')
                self.assertEqual(sockets, [Path('/run/omarchy-kids-controls/sock')])
                events.append(('request', payload))
                if isinstance(result, Exception):
                    raise result
                return result
            stack.enter_context(patch.object(pam_helper.proto, 'request', side_effect=request))
            return pam_helper.main(), events

    def test_root_greeter_drops_all_privilege_before_parent_password_request(self):
        status, events = self.invoke('unlock', {'ok': True, 'mode': 'school'}, b'parent-password\x00')
        self.assertEqual(status, 0)
        self.assertEqual(events[:3], [('groups', []), ('gid', 1000), ('uid', 1000)])
        self.assertEqual(events[3][1], {'scope': 'school', 'cmd': 'free-time.unlock', 'password': 'parent-password'})

    def test_unenrolled_and_root_users_keep_their_existing_login(self):
        self.assertEqual(self.invoke('gate', enrolled=False), (0, []))
        self.assertEqual(self.invoke('gate', user='root'), (0, []))

    def test_enrolled_users_cannot_bypass_expiry_with_errors_wrong_password_or_another_identity(self):
        for result in ({'ok': True, 'free_time_expired': True}, {'ok': True}, {'ok': False}, OSError('offline')):
            self.assertEqual(self.invoke('gate', result, caller=1000)[0], 1)
        self.assertEqual(self.invoke('gate', {'ok': True, 'free_time_expired': False}, caller=1000)[0], 0)
        for result in ({'ok': False, 'error': 'bad_password'}, {'ok': True, 'mode': 'free'}, OSError('offline')):
            self.assertEqual(self.invoke('unlock', result, b'wrong', caller=1000)[0], 1)
        self.assertEqual(self.invoke('unlock', {}, b'anything', caller=1001), (1, []))
        self.assertEqual(self.invoke('unlock', {}, b'anything', pam_type='account'), (1, []))

    def test_missing_status_skips_only_unenrolled_users_and_malformed_status_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'linnea/school-mode/status.json'
            self.assertFalse(pam_helper.enrolled('linnea', root))
            path.parent.mkdir(parents=True)
            path.write_text('malformed')
            self.assertTrue(pam_helper.enrolled('linnea', root))
            path.unlink()
            path.symlink_to(root / 'missing')
            self.assertTrue(pam_helper.enrolled('linnea', root))


if __name__ == '__main__':
    unittest.main()
