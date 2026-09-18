"""Exercise file installation and upgrades in a temporary tree, with systemctl mocked."""
from contextlib import ExitStack
from functools import partial
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'service'))

class Setup(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('game_setup_fixture',ROOT/'service/manage.py')
        self.manage=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.manage)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for directory in ('lib','etc','state','bin','units'):
            (self.root/directory).mkdir()
        m=self.manage
        self.calls,self.enrollments=[],[]
        self.context=ExitStack();self.addCleanup(self.context.close)
        for key,value in {'PREFIX':self.root/'lib/controls','CONFIG':self.root/'etc','STATE':self.root/'state',
            'MARKER':self.root/'etc/installation.json','PASSWORD_PATH':self.root/'etc/password.json',
            'UNIT':self.root/'units/omarchy-kids-controls.service'}.items():
            self.context.enter_context(patch.object(m,key,value))
        original_wrappers=m.wrappers
        self.context.enter_context(patch.object(m,'wrappers',lambda:{self.root/'bin'/p.name:text for p,text in original_wrappers().items()}))
        self.context.enter_context(patch.object(m,'check_account',lambda user:None))
        self.context.enter_context(patch.object(m,'run',lambda *args,**kwargs:self.calls.append(args)))
        self.context.enter_context(patch.object(m,'enroll',lambda *args:self.enrollments.append(args)))
        self.context.enter_context(patch.object(m,'wait_for_service',lambda:None))
        self.context.enter_context(patch.object(m,'remove_game_providers',lambda:None))
        self.context.enter_context(patch.object(m,'replace_screen_time',lambda user:None))
        from omarchy_kids.school_mode import pam_setup
        pam_dir=self.root/'pam.d';pam_dir.mkdir()
        (pam_dir/'omarchy-lock-password').write_text('auth include system-auth\n')
        receipt=self.root/'etc/school-pam.json'
        original_plan,original_install=pam_setup.plan,pam_setup.install
        self.context.enter_context(patch.object(pam_setup,'plan',lambda:original_plan(pam_dir,receipt,os.getuid())))
        self.context.enter_context(patch.object(pam_setup,'install',lambda plan:original_install(plan,pam_dir,receipt)))
        from omarchy_kids.school_mode import websites_setup
        website_etc = self.root / 'browser-etc'; website_etc.mkdir()
        website_plan, website_install = websites_setup.plan, websites_setup.install
        self.context.enter_context(patch.object(websites_setup, 'plan', lambda: website_plan(m.CONFIG, m.STATE, website_etc)))
        self.context.enter_context(patch.object(websites_setup, 'install', lambda previous: website_install(previous, m.CONFIG, m.STATE, website_etc)))
        from omarchy_kids.school_mode import family_dns
        dns_integration = family_dns.Integration
        self.context.enter_context(patch.object(family_dns, 'Integration', lambda: dns_integration(m.CONFIG, website_etc)))
        from omarchy_kids.school_mode import lock_notice_setup
        from test_lock_notice import VIEW
        self.omarchy = self.root / 'omarchy'
        self.lock_view = self.omarchy / lock_notice_setup.RELATIVE_VIEW
        self.lock_view.parent.mkdir(parents=True)
        self.lock_view.write_text(VIEW)
        shell_config = self.omarchy / 'config/omarchy/shell.json'
        shell_config.parent.mkdir(parents=True)
        shell_config.write_text('{}')
        notice_receipt = m.CONFIG / 'school-lock-notice.json'
        notice_plan, notice_install, notice_remove = lock_notice_setup.plan, lock_notice_setup.install, lock_notice_setup.remove
        self.context.enter_context(patch.object(lock_notice_setup, 'read_owned', partial(lock_notice_setup.read_owned, trusted_root=self.root)))
        self.context.enter_context(patch.object(lock_notice_setup, 'plan', lambda path: notice_plan(path, notice_receipt, os.getuid(), m.PREFIX / 'lock-notice/LockNotice.qml')))
        self.context.enter_context(patch.object(lock_notice_setup, 'install', lambda prepared: notice_install(prepared, notice_receipt, os.getuid())))
        self.context.enter_context(patch.object(lock_notice_setup, 'remove', lambda: notice_remove(notice_receipt, os.getuid())))
        original_is_file=Path.is_file
        self.context.enter_context(patch.object(Path,'is_file',lambda path:True if str(path)=='/usr/share/omarchy/config/omarchy/shell.json' else original_is_file(path)))

    def install(self,module,upgrade=True):
        self.manage.install(SimpleNamespace(user='linnea',module=module,upgrade=upgrade,omarchy_path=self.omarchy))

    def test_fresh_install_adds_games_without_enrolling_clocks_or_replacing_parent_data(self):
        m=self.manage
        self.install('grove')
        self.assertFalse(m.PASSWORD_PATH.exists(),'Grove needs no separate controls password')
        self.assertEqual(m.installed()['modules'],['grove'])
        self.assertEqual(self.enrollments,[('grove','linnea',True)])
        self.assertNotIn('schoolModeLockNotice', self.lock_view.read_text())
        self.assertFalse(json.loads((m.CONFIG/'screen-time.json').read_text())['users'])
        password='{"keep":"password hash"}\n';quota='{"users":{"linnea":{"add":5,"multiply":7}}}\n'
        m.PASSWORD_PATH.write_text(password);(m.CONFIG/'pawberry.json').write_text(quota)
        (m.STATE/'saved-counts.json').write_text('{"completed":4}')
        self.install('pawberry');self.install('typing')
        self.assertEqual(m.installed()['modules'],['grove','pawberry','typing'])
        self.assertEqual(m.PASSWORD_PATH.read_text(),password)
        self.assertEqual((m.CONFIG/'pawberry.json').read_text(),quota)
        self.assertEqual((m.STATE/'saved-counts.json').read_text(),'{"completed":4}')
        self.assertEqual(set(x[0] for x in self.enrollments),{'grove','pawberry','typing'})
        self.assertIn(('systemctl','restart','omarchy-kids-controls.service'),self.calls)
        self.assertEqual(m.payload_files(m.PREFIX),m.installed()['payload'])

    def test_unknown_files_and_local_service_edits_stop_upgrade(self):
        m=self.manage
        collision=self.root/'bin/omarchy-kids-controls-grove-client'
        collision.write_text('unrelated command')
        with self.assertRaisesRegex(ValueError,'collision'):
            self.install('grove')
        self.assertEqual(collision.read_text(),'unrelated command')
        collision.unlink()
        self.install('grove')
        target=m.PREFIX/'runtime.py';target.write_text('local administrator change')
        with self.assertRaisesRegex(ValueError,'local edits'):
            self.install('typing')
        self.assertEqual(target.read_text(),'local administrator change')
        self.assertEqual(m.installed()['modules'],['grove'])


    def test_upgrade_removes_old_credit_code_and_preserves_other_modules(self):
        m = self.manage
        m.PASSWORD_PATH.write_text('{"keep":"existing password"}')
        self.install('school')
        marker = m.installed()
        obsolete = m.PREFIX / 'omarchy_kids/core/game_platform.py'
        obsolete.write_text('# former credit transport')
        marker.update(version='3.0.1', payload=m.payload_files(m.PREFIX))
        m.write_json(m.MARKER, marker)
        school = '{"users":{"linnea":{"enabled":true,"apps":["chromium"]}}}'
        (m.CONFIG/'school-mode.json').write_text(school)
        with patch.object(m, 'remove_game_providers') as remove:
            self.install('pawberry')
            remove.assert_called_once_with()
        self.assertFalse(obsolete.exists())
        self.assertEqual(m.installed()['version'], '4.4.0')
        self.assertEqual(m.installed()['modules'], ['pawberry', 'school'])
        self.assertEqual((m.CONFIG/'school-mode.json').read_text(), school)
        self.assertNotIn('/var/lib/peterholko-screen-time', m.UNIT.read_text())

    def test_school_upgrade_keeps_games_parent_password_school_apps_and_completed_counts(self):
        m=self.manage
        self.install('grove')
        marker=m.installed();marker['version']='4.0.0';m.write_json(m.MARKER,marker)
        password='{"hash":"existing controls password"}'
        school='{"users":{"linnea":{"profile":"linnea"}},"profiles":{"linnea":{"school_apps":["chromium"]}}}'
        m.PASSWORD_PATH.write_text(password)
        (m.CONFIG/'school-mode.json').write_text(school)
        counts=m.STATE/'pawberry-counts.json';counts.write_text('{"multiply":7}')
        self.install('school')
        self.assertEqual(m.installed()['modules'],['grove','school'])
        self.assertEqual(m.PASSWORD_PATH.read_text(),password)
        self.assertEqual((m.CONFIG/'school-mode.json').read_text(),school)
        self.assertEqual(counts.read_text(),'{"multiply":7}')
        self.assertTrue((self.root/'bin/omarchy-kids-controls-school-pam').is_file())
        self.assertTrue((m.CONFIG/'school-pam.json').is_file())
        self.assertTrue((m.PREFIX/'lock-notice/LockNotice.qml').is_file())
        self.assertIn('schoolModeLockNotice', self.lock_view.read_text())

    def test_removing_school_restores_lock_view_and_keeps_the_game_module(self):
        from test_lock_notice import VIEW
        m = self.manage
        m.PASSWORD_PATH.write_text('{"hash":"existing controls password"}')
        self.install('grove')
        self.install('school')
        from omarchy_kids.school_mode import pam_setup, websites_setup
        with patch.object(pam_setup, 'remove'), patch.object(websites_setup, 'remove'):
            m.remove('school')
        self.assertEqual(self.lock_view.read_text(), VIEW)
        self.assertFalse((m.CONFIG/'school-lock-notice.json').exists())
        self.assertEqual(m.installed()['modules'], ['grove'])
        self.assertTrue(m.PREFIX.exists())

    def test_browser_preparation_failure_can_resume_with_the_verified_previous_unit(self):
        from omarchy_kids.school_mode import websites_setup
        m = self.manage
        m.PASSWORD_PATH.write_text('{"hash":"existing controls password"}')
        self.install('school')
        marker = m.installed()
        old_unit = marker['unit'].replace('ReadWritePaths=-/etc/chromium/policies/managed -/etc/opt/chrome/policies/managed\n', '')
        marker.update(version='4.1.0', unit=old_unit)
        m.write_json(m.MARKER, marker)
        m.UNIT.write_text(old_unit)
        with patch.object(websites_setup, 'install', side_effect=OSError('fixture interrupted browser setup')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                self.install('school')
        self.assertEqual(m.installed()['previous_unit'], old_unit)
        self.install('school')
        self.assertNotIn('previous_unit', m.installed())
        self.assertIn('/etc/chromium/policies/managed', m.UNIT.read_text())


class ProviderRemoval(unittest.TestCase):
    def test_cleanup_removes_only_the_three_game_registrations_and_reports_errors(self):
        spec = importlib.util.spec_from_file_location('provider_cleanup_fixture', ROOT/'service/manage.py')
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        with patch.object(Path, 'is_file', return_value=True), patch.object(m, 'run') as run:
            run.return_value = SimpleNamespace(stdout='{"ok":true}')
            m.remove_game_providers()
            self.assertEqual([call.args for call in run.call_args_list], [
                ('/usr/bin/omarchy-peterholko-screen-time-admin', 'provider-remove', provider)
                for provider in ('peterholko.pawberry', 'peterholko.number-grove', 'peterholko.paw-post')])
            run.return_value = SimpleNamespace(stdout='{"ok":false,"error":"service_error"}')
            with self.assertRaisesRegex(ValueError, 'could not remove'):
                m.remove_game_providers()
        with patch.object(Path, 'is_file', return_value=False), patch.object(m, 'run') as run:
            m.remove_game_providers()
            run.assert_not_called()

    def test_replacing_a_timer_targets_only_the_named_child_and_keeps_a_recovery_record(self):
        spec = importlib.util.spec_from_file_location('timer_replacement_fixture', ROOT/'service/manage.py')
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        original_read = m.read_json
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as context:
            directory = Path(temporary)
            context.enter_context(patch.object(m, 'CONFIG', directory))
            m.write_json(m.config_path('time'), {'users': {'linnea': {}, 'other-child': {}}})
            def read(path, default):
                if str(path) == '/etc/peterholko-screen-time/config.json':
                    return {'users': {'linnea': {'profile': 'existing'}, 'other-child': {'profile': 'other'}}}
                return original_read(path, default)
            context.enter_context(patch.object(m, 'read_json', side_effect=read))
            context.enter_context(patch.object(Path, 'is_file', return_value=True))
            context.enter_context(patch.object(m.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000)))
            enroll = context.enter_context(patch.object(m, 'enroll'))
            run = context.enter_context(patch.object(m, 'run', return_value=SimpleNamespace(stdout='{"ok":true}')))
            m.replace_screen_time('linnea')
            enroll.assert_called_once_with('time', 'linnea', False)
            self.assertEqual(run.call_args.args, ('/usr/bin/omarchy-peterholko-screen-time-admin', 'remove', 'linnea'))
            self.assertEqual(json.loads((directory/'previous-screen-time-1000.json').read_text()),
                             {'user': 'linnea', 'enrollment': {'profile': 'existing'}})
            run.return_value.stdout = '{"ok":false}'
            with self.assertRaisesRegex(ValueError, 'could not disable'):
                m.replace_screen_time('linnea')

if __name__=='__main__':
    unittest.main()
