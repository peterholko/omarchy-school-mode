"""Website policy and signed browser integration, entirely in temporary trees."""
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'service'))
from omarchy_kids.school_mode import config, domains, websites_setup as setup, websites_native as native
from omarchy_kids.school_mode.websites import AssetServer
import test_free_time as timer_fixtures


class Domains(unittest.TestCase):
    def test_normalization_duplicates_and_subdomain_format(self):
        self.assertEqual(domains.normalize_domains([' YOUTUBE.com ', '*.youtube.com.', 'www.youtube.com', 'xn--bcher-kva.de']),
                         ['www.youtube.com', 'xn--bcher-kva.de', 'youtube.com'])
        for item in ('https://youtube.com/watch', 'example.com:443', 'a.com/x', '*', 'com', '.example.com',
                     '-bad.com', 'a..com', '127.0.0.1', 'a' * 64 + '.com', 'bücher.de', 'example.com\nother.com'):
            with self.subTest(item=item), self.assertRaises(ValueError):
                domains.normalize_domains([item])
        self.assertFalse(config.valid_patch({'websites_enabled': 'yes'}))
        self.assertFalse(config.valid_patch({'school_blocked_domains': ['bad']}))
        self.assertFalse(config.valid_patch({'school_blocked_domains': ['a.com'] * 101}))
        self.assertFalse(config.sanitize_profile({})['websites_enabled'])


class Integration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config, self.state, self.etc = [self.root / name for name in ('config', 'state', 'etc')]
        for directory in (self.config, self.state, self.etc):
            directory.mkdir()

    def install(self):
        return setup.install(setup.plan(self.config, self.state, self.etc), self.config, self.state, self.etc)

    def test_upgrade_stable_identity_key_and_removal_preserve_other_policies(self):
        first = self.install()
        key = (self.config / 'school-websites-key.pem').read_bytes()
        unrelated = setup.policy_paths(self.etc)[0].with_name('administrator.json')
        unrelated.write_text('{"HomepageLocation":"https://school.example"}')
        self.assertEqual(self.install()['extension_id'], first['extension_id'])
        self.assertEqual((self.config / 'school-websites-key.pem').read_bytes(), key)
        self.assertEqual((self.config / 'school-websites-key.pem').stat().st_mode & 0o777, 0o600)
        for path in setup.policy_paths(self.etc):
            self.assertEqual(json.loads(path.read_text()), {})  # Off by default.
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        setup.remove(self.config, self.state, self.etc)
        self.assertTrue(unrelated.exists())
        self.assertTrue((self.config / 'school-websites-key.pem').exists())
        self.assertFalse(any(p.exists() for p in setup.policy_paths(self.etc) + setup.host_paths(self.etc)))

    def test_collisions_modified_native_hosts_and_policy_conflicts(self):
        target = setup.policy_paths(self.etc)[0]
        target.parent.mkdir(parents=True); target.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'collision'):
            setup.plan(self.config, self.state, self.etc)
        target.unlink()
        self.install()
        unrelated = target.with_name('other.json'); unrelated.write_text('{"URLAllowlist":["youtube.com"]}')
        self.assertIn('URLAllowlist', setup.conflicts(self.etc)[0])
        self.assertEqual(json.loads(unrelated.read_text()), {'URLAllowlist': ['youtube.com']})
        host = setup.host_paths(self.etc)[0]; host.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'edited'):
            setup.remove(self.config, self.state, self.etc)
        self.assertTrue(target.exists())

    def test_unknown_symlink_ancestor_is_rejected(self):
        (self.etc / 'chromium').symlink_to(self.state, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'owned'):
            setup.plan(self.config, self.state, self.etc)

    def test_crx3_signature_and_id_match_native_host(self):
        receipt = self.install()
        crx = (self.state / 'school-websites/school.crx').read_bytes()
        self.assertEqual(crx[:4], b'Cr24')
        version, size = struct.unpack('<II', crx[4:12]); self.assertEqual(version, 3)
        def fields(data):
            position = 0; result = {}
            def integer():
                nonlocal position
                number, shift = 0, 0
                while True:
                    value = data[position]; position += 1
                    number |= (value & 127) << shift
                    if value < 128:
                        return number
                    shift += 7
            while position < len(data):
                tag, length = integer(), integer()
                self.assertEqual(tag & 7, 2)
                result[tag >> 3] = data[position:position + length]; position += length
            return result
        header = fields(crx[12:12+size]); proof = fields(header[2]); signed = header[10000]
        self.assertEqual(fields(signed)[1], hashlib.sha256(proof[1]).digest()[:16])
        key = self.root / 'public.der'; key.write_bytes(proof[1])
        pem = setup.openssl('pkey', '-pubin', '-inform', 'DER', '-in', str(key), '-outform', 'PEM')
        key.write_bytes(pem)
        signature = self.root / 'signature'; signature.write_bytes(proof[2])
        result = setup.openssl('dgst', '-sha256', '-verify', str(key), '-signature', str(signature),
            data=b'CRX3 SignedData\0' + struct.pack('<I', len(signed)) + signed + crx[12+size:])
        self.assertIn(b'Verified OK', result)
        host = json.loads(setup.host_paths(self.etc)[0].read_text())
        self.assertEqual(host['allowed_origins'], ['chrome-extension://' + receipt['extension_id'] + '/'])

    def test_asset_server_only_serves_fixed_public_assets(self):
        self.install()
        server = AssetServer(self.state / 'school-websites', port=0)
        self.addCleanup(server.close)
        address, port = server.server.server_address
        self.assertEqual(address, '127.0.0.1')
        with urlopen(f'http://127.0.0.1:{port}/update.xml?x=browser-metadata') as reply:
            self.assertIn(b'<gupdate', reply.read())
        for path in ('/../config/school-websites-key.pem', '/installation.json', '/update.xml/extra'):
            with self.assertRaises(HTTPError) as error:
                urlopen(f'http://127.0.0.1:{port}' + path)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()


class NativeProtocol(unittest.TestCase):
    def test_round_trip_truncation_and_size_bounds(self):
        stream = io.BytesIO(); native.write_frame(stream, {'type': 'poll'}); stream.seek(0)
        self.assertEqual(native.read_frame(stream), {'type': 'poll'})
        for stream in (io.BytesIO(b'\x01'), io.BytesIO(struct.pack('=I', 10) + b'{}')):
            with self.assertRaises(EOFError): native.read_frame(stream)
        with self.assertRaises(ValueError): native.read_frame(io.BytesIO(struct.pack('=I', native.MAX_FRAME + 1)))

    def test_bridge_cannot_relay_commands_passwords_or_other_users(self):
        calls = []
        request = lambda value: calls.append(value)
        native.relay({'type': 'poll'}, request)
        native.relay({'type': 'ack', 'generation': 'digest', 'instance': 'test'}, request)
        for value in ({'type': 'poll', 'user': 'root'}, {'type': 'config.patch', 'password': 'secret'},
                      {'type': 'ack', 'generation': 'x', 'instance': 'test', 'cmd': 'mode.set'}):
            with self.assertRaises(ValueError): native.relay(value, request)
        self.assertEqual(calls[0], {'scope': 'school', 'cmd': 'websites.status'})
        self.assertEqual(calls[1]['cmd'], 'websites.ack')


# Reuse the existing isolated real-daemon fixture, not its timer test methods.
class WebsiteService(unittest.TestCase):
    setUp = timer_fixtures.ServiceTests.setUp
    start_daemon = timer_fixtures.ServiceTests.start_daemon
    request = timer_fixtures.ServiceTests.request
    parent = timer_fixtures.ServiceTests.parent

    def prepare(self):
        web = self.daemon.services['school'].websites
        web.etc.mkdir()
        setup.install(setup.plan(web.config_dir, web.directory.parent, web.etc), web.config_dir, web.directory.parent, web.etc)
        self.context.enter_context(patch('omarchy_kids.school_mode.websites.AssetServer'))
        return web

    def test_auth_modes_expired_unlock_restart_and_disabled_enrollment(self):
        web = self.prepare()
        settings = {'websites_enabled': True, 'school_blocked_domains': ['youtube.com']}
        self.assertFalse(self.request({'cmd': 'config.patch', 'patch': settings})['ok'])
        self.assertTrue(self.parent(cmd='config.patch', patch=settings)['ok'])
        self.assertEqual(web.domains, ['youtube.com'])
        policy = setup.policy_paths(web.etc)[0]
        self.assertEqual(json.loads(policy.read_text())['URLBlocklist'], ['youtube.com'])
        generation = web.generation
        self.request({'cmd': 'websites.ack', 'generation': generation, 'instance': 'one'})
        self.assertTrue(web.status(1000)['browserReceived'])
        self.parent(cmd='mode.set', mode='free')
        self.assertEqual(web.domains, [])
        self.assertNotIn('URLBlocklist', json.loads(policy.read_text()))
        self.assertFalse(web.status(1000)['browserReceived'])
        self.now += 1800
        self.daemon.refresh(self.now)
        self.assertEqual(web.domains, [])  # Timer expiry is still Free Time until parent unlock.
        self.parent(cmd='free-time.unlock')
        self.assertEqual(web.domains, ['youtube.com'])
        self.start_daemon(); self.daemon.refresh(self.now)
        self.assertEqual(self.daemon.services['school'].websites.domains, ['youtube.com'])
        self.daemon.dispatch(0, {'scope': 'school', 'cmd': 'users.set', 'user': 'linnea', 'enabled': False})
        self.assertEqual(json.loads(policy.read_text()), {})

    def test_conflict_and_missing_setup_fail_before_saving(self):
        settings = {'websites_enabled': True, 'school_blocked_domains': ['youtube.com']}
        self.assertEqual(self.parent(cmd='config.patch', patch=settings)['error'], 'websites_setup')
        web = self.prepare()
        extra = setup.policy_paths(web.etc)[0].with_name('external.json')
        extra.write_text('{"URLBlocklist":["unrelated.example"]}')
        result = self.parent(cmd='config.patch', patch=settings)
        self.assertEqual(result['error'], 'websites_setup')
        self.assertFalse(web.school.policy_for(1000).profile['websites_enabled'])
        self.assertEqual(json.loads(extra.read_text()), {'URLBlocklist': ['unrelated.example']})
        self.assertEqual(self.parent(cmd='config.patch', patch={'school_blocked_domains': ['https://bad']})['error'], 'bad_domains')

    def test_schedule_applies_domains_and_disabling_feature_restores_only_owned_policy(self):
        web = self.prepare()
        self.parent(cmd='config.patch', patch={'websites_enabled': True, 'school_blocked_domains': ['youtube.com'],
            'blocked_periods': [{'enabled': True, 'start': '10:10', 'end': '11:00', 'days': ['mon']}]})
        unrelated = setup.policy_paths(web.etc)[0].with_name('homepage.json')
        unrelated.write_text('{"HomepageLocation":"https://school.example"}')
        self.parent(cmd='mode.set', mode='free')
        self.now += 600; self.daemon.refresh(self.now)
        self.assertEqual(web.domains, ['youtube.com'])
        self.parent(cmd='config.patch', patch={'websites_enabled': False})
        self.assertEqual(json.loads(setup.policy_paths(web.etc)[0].read_text()), {})
        self.assertEqual(json.loads(unrelated.read_text()), {'HomepageLocation': 'https://school.example'})
        self.lock_call.assert_not_called()

    def test_old_or_malformed_ack_does_not_claim_browser_updated(self):
        web = self.prepare()
        self.parent(cmd='config.patch', patch={'websites_enabled': True, 'school_blocked_domains': ['youtube.com']})
        self.assertFalse(self.request({'cmd': 'websites.ack', 'generation': 'old', 'instance': 'x'})['ok'])
        self.assertFalse(self.request({'cmd': 'websites.ack', 'generation': web.generation, 'instance': '../../x'})['ok'])
        self.assertFalse(web.status(1000)['browserReceived'])
        self.assertNotIn('users', self.request({'cmd': 'websites.status'}))

    def test_later_policy_or_updater_error_cannot_leave_school_blocking_in_free_time(self):
        web = self.prepare()
        self.parent(cmd='config.patch', patch={'websites_enabled': True, 'school_blocked_domains': ['youtube.com']})
        extra = setup.policy_paths(web.etc)[0].with_name('external.json')
        extra.write_text('{"URLAllowlist":["example.com"]}')
        web.last_conflict_check = -100
        self.parent(cmd='mode.set', mode='free')
        self.assertNotIn('URLBlocklist', json.loads(setup.policy_paths(web.etc)[0].read_text()))
        self.assertIn('conflict', web.error)
        extra.unlink()
        self.parent(cmd='mode.set', mode='school')
        web.asset_server = None
        with patch('omarchy_kids.school_mode.websites.AssetServer', side_effect=OSError('occupied')):
            self.parent(cmd='mode.set', mode='free')
        self.assertNotIn('URLBlocklist', json.loads(setup.policy_paths(web.etc)[0].read_text()))
        self.assertEqual(web.domains, [])
        self.assertIn('port', web.error)

    def test_multiple_accounts_keep_only_the_union_of_current_school_rules(self):
        web = self.prepare()
        accounts = {'linnea': SimpleNamespace(pw_uid=1000, pw_name='linnea'),
                    'other': SimpleNamespace(pw_uid=1001, pw_name='other')}
        with patch('pwd.getpwnam', side_effect=lambda name: accounts[name]), \
                patch('omarchy_kids.core.session.username_for', side_effect=lambda uid: {1000: 'linnea', 1001: 'other'}[uid]):
            self.daemon.dispatch(0, {'scope': 'school', 'cmd': 'users.set', 'user': 'other'})
            self.parent(cmd='config.patch', patch={'websites_enabled': True, 'school_blocked_domains': ['youtube.com']})
            result = self.daemon.dispatch(0, {'scope': 'school', 'user': 'other', 'cmd': 'config.patch',
                'patch': {'websites_enabled': True, 'school_blocked_domains': ['roblox.com']}})
            self.assertTrue(result['ok'])
            self.assertEqual(web.domains, ['roblox.com', 'youtube.com'])
            self.parent(cmd='mode.set', mode='free')
            self.assertEqual(web.domains, ['roblox.com'])
            self.assertTrue(web.status(1000)['otherAccounts'])
            self.daemon.dispatch(0, {'scope': 'school', 'cmd': 'mode.set', 'mode': 'free', 'user': 'other'})
            self.assertEqual(web.domains, [])


if __name__ == '__main__':
    unittest.main()
