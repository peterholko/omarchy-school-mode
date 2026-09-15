"""Exercise policy, service persistence and the real PAM helper protocol."""
from contextlib import ExitStack
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'service'))
from omarchy_kids.core import paths, session
from omarchy_kids.core.clock import Clock
from omarchy_kids.core.daemon import Daemon
from omarchy_kids.school_mode import config, pam_helper, pam_setup
from omarchy_kids.school_mode.policy import Policy

NOW = datetime(2026, 9, 14, 10).timestamp()


class PolicyTests(unittest.TestCase):
    def policy(self, **options):
        return Policy(config.sanitize_profile(options))

    def test_only_parent_activation_grants_the_configured_allowance(self):
        p = self.policy()
        self.assertEqual(p.snapshot(NOW)['mode'], 'school')
        self.assertFalse(p.set_mode('free', NOW, False)['ok'])
        self.assertEqual(p.set_mode('free', NOW, True)['free_time_remaining_seconds'], 1800)
        self.assertEqual(p.snapshot(NOW + 60)['free_time_remaining_seconds'], 1740)
        p.profile['free_time_minutes'] = 15
        self.assertEqual(p.snapshot(NOW + 120)['free_time_remaining_seconds'], 1680)
        p.set_mode('school', NOW + 120, False)
        self.assertEqual(p.set_mode('free', NOW + 120, True)['free_time_remaining_seconds'], 900)

    def test_expiry_survives_restart_and_requires_parent_to_return_to_school(self):
        p = self.policy()
        p.set_mode('free', NOW, True)
        p2 = self.policy()
        p2.restore_override(p.export_override(), NOW + 600)
        self.assertEqual(p2.snapshot(NOW + 600)['free_time_remaining_seconds'], 1200)
        self.assertTrue(p2.snapshot(NOW + 1800)['free_time_expired'])
        saved = json.loads(json.dumps(p2.export_override()))
        p3 = self.policy()
        p3.restore_override(saved, NOW + 3600)
        for mode in ('school', 'auto', 'free'):
            self.assertFalse(p3.set_mode(mode, NOW + 3600, False)['ok'])
        self.assertFalse(p3.set_mode('free', NOW + 3600, True)['ok'])
        self.assertEqual(p3.set_mode('school', NOW + 3600, True)['mode'], 'school')
        self.assertFalse(p3.snapshot(NOW + 86400)['free_time_expired'])
        self.assertEqual(p3.snapshot(NOW + 86400)['free_time_remaining_seconds'], 0)

    def test_reboot_does_not_discard_an_expired_deadline(self):
        p = self.policy()
        p.set_mode('free', NOW, True)
        restored = self.policy()
        restored.restore_override(p.export_override(), NOW + 1801)
        self.assertTrue(restored.snapshot(NOW + 1801)['free_time_expired'])

    def test_school_cancels_the_timer_and_never_expires(self):
        p = self.policy()
        p.set_mode('free', NOW, True)
        self.assertTrue(p.set_mode('school', NOW + 900, False)['ok'])
        state = p.snapshot(NOW + 7200)
        self.assertEqual(state['mode'], 'school')
        self.assertFalse(state['free_time_expired'])
        self.assertEqual(state['free_time_remaining_seconds'], 0)

    def test_schedule_preempts_active_allowance_and_ending_school_does_not_grant_time(self):
        p = self.policy(blocked_periods=[{'enabled': True, 'start': '10:10', 'end': '10:20', 'days': ['mon']}])
        p.set_mode('free', NOW, True)
        self.assertEqual(p.snapshot(NOW + 600)['mode'], 'school')
        self.assertEqual(p.snapshot(NOW + 1800)['mode'], 'school')
        self.assertFalse(p.snapshot(NOW + 1800)['free_time_expired'])

    def test_parent_can_grant_time_during_school_hours(self):
        p = self.policy(blocked_periods=[{'enabled': True, 'start': '09:00', 'end': '15:00', 'days': ['mon']}])
        p.set_mode('free', NOW, True)
        self.assertEqual(p.snapshot(NOW + 60)['mode'], 'free')
        self.assertTrue(p.snapshot(NOW + 1800)['free_time_expired'])

    def test_reboot_settles_the_first_event_even_if_school_hours_have_come_and_gone(self):
        for start, should_expire in (('10:10', False), ('10:40', True)):
            p = self.policy(blocked_periods=[{'enabled': True, 'start': start, 'end': '11:00', 'days': ['mon']}])
            p.set_mode('free', NOW, True)
            restored = self.policy(**p.profile)
            restored.restore_override(p.export_override(), NOW + 7200)
            self.assertEqual(restored.snapshot(NOW + 7200)['free_time_expired'], should_expire)
            self.assertEqual(restored.snapshot(NOW + 7200)['mode'], 'free' if should_expire else 'school')

    def test_allowance_can_cross_midnight_and_the_end_of_school_hours(self):
        p = self.policy()
        late = datetime(2026, 9, 14, 23, 50).timestamp()
        p.set_mode('free', late, True)
        self.assertTrue(p.snapshot(late + 1800)['free_time_expired'])
        p = self.policy(blocked_periods=[{'enabled': True, 'start': '09:00', 'end': '10:10', 'days': ['mon']}])
        p.set_mode('free', NOW, True)
        self.assertTrue(p.snapshot(NOW + 1800)['free_time_expired'])

    def test_old_unlimited_override_is_not_migrated_into_unattended_free_time(self):
        p = self.policy()
        p.restore_override({'mode_override': 'free', 'mode_override_by_parent': True, 'mode_override_until': NOW + 7200}, NOW)
        self.assertEqual(p.snapshot(NOW)['mode'], 'school')

    def test_clock_rollback_cannot_increase_remaining_minutes(self):
        p = self.policy()
        p.set_mode('free', NOW, True)
        self.assertEqual(p.snapshot(NOW + 100)['free_time_remaining_seconds'], 1700)
        self.assertEqual(p.snapshot(NOW - 100)['free_time_remaining_seconds'], 1700)

    def test_duration_validation_rejects_booleans_fractions_and_unbounded_values(self):
        for value in (False, 0, -1, 1441, 3.5, '30', None):
            self.assertFalse(config.valid_patch({'free_time_minutes': value}))
        for value in (1, 30, 1440):
            self.assertTrue(config.valid_patch({'free_time_minutes': value}))

    def test_small_wall_clock_rollback_and_suspend_do_not_pause_the_clock(self):
        with patch('time.clock_gettime', side_effect=[0, 60, 1800]), patch('time.time', side_effect=[NOW, NOW - 10, NOW + 1800]):
            clock = Clock()
            self.assertEqual(clock.tick(), (NOW + 60, 60))
            self.assertEqual(clock.tick(), (NOW + 1800, 1740))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(patch.dict(os.environ, {'SCREEN_TIME_ROOT': str(self.root)}))
        account = SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_name='linnea')
        self.context.enter_context(patch('pwd.getpwnam', return_value=account))
        self.context.enter_context(patch.object(session, 'username_for', return_value='linnea'))
        self.context.enter_context(patch.object(pam_setup, 'ready', return_value=True))
        self.watcher = SimpleNamespace(present=True, locked=False, session_id='3')
        self.watcher.poll = lambda: self.watcher
        self.context.enter_context(patch.object(session, 'SessionWatcher', return_value=self.watcher))
        self.lock_call = self.context.enter_context(patch.object(session, 'lock', return_value='fixture lock'))
        self.context.enter_context(patch.object(session, 'notify'))
        self.now = NOW
        self.start_daemon()
        self.daemon.dispatch(0, {'scope': 'school', 'cmd': 'users.set', 'user': 'linnea'})

    def start_daemon(self):
        self.daemon = Daemon(paths.detect(), modules=['school'], log=lambda value: None)
        self.daemon.clock = SimpleNamespace(now=lambda: self.now)
        self.daemon.auth.verifier = lambda user, password: password == 'fixture-parent-secret'

    def request(self, payload):
        return self.daemon.dispatch(1000, {'scope': 'school', **payload})

    def parent(self, **payload):
        return self.request({'password': 'fixture-parent-secret', **payload})

    def test_manual_lock_allows_normal_unlock_until_expiry_then_requires_parent(self):
        self.assertTrue(self.parent(cmd='mode.set', mode='free')['ok'])
        self.watcher.locked = True
        self.now += 300
        self.assertTrue(pam_helper.authenticate('gate', self.request))
        self.daemon.refresh(self.now)
        self.lock_call.assert_not_called()
        self.now += 1500
        self.assertFalse(pam_helper.authenticate('gate', self.request))
        self.daemon.refresh(self.now)
        self.lock_call.assert_not_called()  # Already locked: change the authentication rule only.
        self.assertFalse(pam_helper.authenticate('unlock', self.request, 'fixture-child-secret'))
        self.assertTrue(pam_helper.authenticate('unlock', self.request, 'fixture-parent-secret'))
        state = self.request({'cmd': 'status'})
        self.assertEqual(state['mode'], 'school')
        self.assertFalse(state['free_time_expired'])
        self.assertEqual(state['free_time_remaining_seconds'], 0)
        self.assertTrue(pam_helper.authenticate('gate', self.request))

    def test_expiry_requests_lock_and_retries_but_school_never_locks(self):
        self.daemon.refresh(self.now)
        self.lock_call.assert_not_called()
        self.parent(cmd='mode.set', mode='free')
        self.now += 1800
        self.daemon.refresh(self.now)
        self.lock_call.assert_called_once_with(1000, '3')
        self.now += 5
        self.daemon.refresh(self.now)
        self.assertEqual(self.lock_call.call_count, 2)
        self.parent(cmd='free-time.unlock')
        self.now += 7200
        self.daemon.refresh(self.now)
        self.assertEqual(self.lock_call.call_count, 2)

    def test_expired_state_persists_and_cannot_be_cleared_by_child_mode_or_config_requests(self):
        self.parent(cmd='mode.set', mode='free')
        self.now += 1800
        self.assertTrue(self.request({'cmd': 'status'})['free_time_expired'])
        self.start_daemon()
        self.assertTrue(self.request({'cmd': 'status'})['free_time_expired'])
        for mode in ('school', 'auto', 'free'):
            self.assertFalse(self.request({'cmd': 'mode.set', 'mode': mode})['ok'])
        self.assertFalse(self.request({'cmd': 'config.patch', 'patch': {'free_time_minutes': 1000}})['ok'])
        self.assertTrue(self.request({'cmd': 'status'})['free_time_expired'])

    def test_pam_guards_check_expiry_again_after_normal_child_authentication(self):
        self.parent(cmd='mode.set', mode='free')
        self.now += 1799
        self.assertTrue(pam_helper.authenticate('gate', self.request))
        self.now += 2
        self.assertFalse(pam_helper.authenticate('gate', self.request))

    def test_free_time_requires_installed_parent_lock_authentication(self):
        with patch.object(pam_setup, 'ready', return_value=False):
            self.assertEqual(self.parent(cmd='mode.set', mode='free')['error'], 'timer_setup_required')
        self.assertEqual(self.request({'cmd': 'status'})['mode'], 'school')

    def test_daemon_wakes_at_expiry_instead_of_waiting_for_another_poll(self):
        school = self.daemon.services['school']
        self.assertEqual(school.next_delay(self.now, 5), 5)
        self.parent(cmd='mode.set', mode='free')
        self.assertEqual(school.next_delay(self.now + 1798, 5), 2)
        self.now += 1800
        self.daemon.refresh(self.now)
        self.lock_call.assert_called_once()
        self.assertEqual(school.next_delay(self.now, 5), 5)


if __name__ == '__main__':
    unittest.main()
