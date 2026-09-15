"""Local protocol tests. No system install, sudo, network, or desktop required."""
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import pwd
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'service'))
from omarchy_kids.core import paths, storage
from omarchy_kids.core.auth import ParentAuth
from omarchy_kids.core.daemon import Daemon
PROVIDERS = {'pawberry': ('peterholko.pawberry', 'Pawberry', 'problem'),
    'grove': ('peterholko.number-grove', 'Grove', 'challenge'),
    'typing': ('peterholko.paw-post', 'Paw Post', 'delivery')}
from omarchy_kids.pawberry import work
from omarchy_kids.pawberry.service import answer_for


class Games(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.uid = os.getuid() or pwd.getpwnam('nobody').pw_uid
        self.user = pwd.getpwuid(self.uid).pw_name
        self.now = time.time()
        self.host = Daemon(paths.detect(self.root), modules=['pawberry', 'grove', 'typing'], log=lambda *args: None)
        self.host.clock.now = lambda: self.now
        self.host.auth = ParentAuth(verifier=lambda username, password: password == 'parent-secret')
        for module in PROVIDERS:
            self.assertTrue(self.send(module, 'users.set', peer=0, user=self.user, enabled=True)['ok'])

    def advance(self, seconds=10):
        self.now += seconds

    def send(self, scope, cmd, peer=None, **message):
        return self.host.dispatch(self.uid if peer is None else peer, {'scope': scope, 'cmd': cmd, **message})

    def pawberry(self, operation='add', **extra):
        a, b = (18, 3) if operation == 'divide' else (8, 7) if operation == 'multiply' else (61, 29)
        return self.send('pawberry', 'begin', protocol=2, problem={'operation': operation, 'a': a, 'b': b}, **extra)

    def solve_pet(self, started):
        self.advance()
        return self.send('pawberry', 'complete', id=started['id'], answer=answer_for(started['problem']), steps=work.expected_steps(started['problem']))

    def test_only_requested_games_are_loaded_and_cannot_grant_arbitrary_time(self):
        self.assertEqual(set(self.host.services), {'pawberry', 'grove', 'typing'})
        for module in self.host.services:
            self.assertFalse(self.send(module, 'grant', seconds=3600)['ok'])
            self.assertFalse(self.send(module, 'users.set', user='root', enabled=True)['ok'])
        self.assertFalse(self.send('time', 'status')['ok'])
        result = self.send('grove', 'begin', grade=6, user='root', correct=True, seconds=3600)
        self.assertTrue(result['ok'])
        self.assertNotIn('answer', result['question'])
        self.assertFalse(hasattr(self.host, 'platform'))

    def test_pawberry_parent_limits_and_settings_keep_todays_work(self):
        started = self.pawberry('multiply')
        self.assertTrue(self.solve_pet(started)['ok'])
        bad = self.send('pawberry', 'limits.set', limits={'multiply': 0}, password='wrong')
        self.assertEqual(bad['error'], 'bad_password')
        saved = self.send('pawberry', 'limits.set', limits={'add': 5, 'subtract': 5, 'multiply': 1}, password='parent-secret')
        self.assertEqual(saved['completed']['multiply'], 1)
        self.assertEqual(saved['remaining']['multiply'], 0)
        self.assertEqual(self.pawberry('multiply')['error'], 'daily_limit')
        self.assertTrue(self.pawberry('divide')['ok'])
        replay = self.solve_pet(started)
        self.assertTrue(replay['already_completed'])
        self.assertEqual(replay['completed']['multiply'], 1)

    def test_pawberry_requires_all_work_and_server_issued_problem(self):
        started = self.pawberry()
        pending = self.host.services['pawberry'].account(self.uid)['pending']
        self.assertEqual(started['problem']['a'], pending['a'])
        identifier, problem = started['id'], started['problem']
        correct = answer_for(problem)
        self.advance()
        for steps in (None, [], [{'kind': 'final', 'value': correct}], [{'kind': 'final', 'value': True}]):
            self.assertEqual(self.send('pawberry', 'complete', id=identifier, answer=correct, steps=steps)['error'], 'incomplete_work')
        self.assertEqual(self.send('pawberry', 'complete', id=identifier, answer=correct+1, steps=work.expected_steps(problem))['error'], 'incorrect_answer')
        self.assertFalse(hasattr(self.host, 'platform'))
        self.assertTrue(self.solve_pet(started)['ok'])
        legacy = self.send('pawberry', 'begin', problem={'operation': 'add', 'a': 11, 'b': 12})
        self.assertTrue(legacy['ok'])

    def test_parent_settings_cannot_reenable_time_rewards(self):
        for backend in ('legacy', 'platform'):
            result = self.send('pawberry', 'settings.set', password='parent-secret',
                limits={'add': 5}, screen_time={'enabled': True, 'backend': backend})
            self.assertEqual(result['error'], 'rewards_removed')
        status = self.send('pawberry', 'status')
        self.assertTrue(status['practice_only'])
        self.assertNotIn('screen_time', status)

    def test_grove_grades_answers_and_replays(self):
        grove = self.host.services['grove']
        for grade in (5, 6):
            for _ in range(80):
                problem = grove.challenge({'grade': grade})
                self.assertTrue('×' in problem['text'] or '÷' in problem['text'])
                self.assertEqual(len(set(problem['choices'])), 6)
        for grade in (True, '5', {}, 0, 7):
            self.assertEqual(self.send('grove', 'begin', grade=grade)['error'], 'invalid_challenge')
        started = self.send('grove', 'begin', grade=5)
        pending = grove.account(self.uid)['pending']
        self.assertEqual(self.send('grove', 'complete', id=pending['id'], answer=pending['answer'])['error'], 'too_fast')
        self.advance()
        self.assertFalse(self.send('grove', 'complete', id=pending['id'], answer=True)['ok'])
        result = self.send('grove', 'complete', id=pending['id'], answer=pending['answer'])
        self.assertTrue(result['correct'])
        replay = self.send('grove', 'complete', id=pending['id'], answer=0)
        self.assertTrue(replay['already_completed'])
        self.assertEqual(replay['reward_seconds'], 0)
        self.send('grove', 'begin', grade=5)
        pending = grove.account(self.uid)['pending']; self.advance()
        wrong = next(n for n in pending['choices'] if n != pending['answer'])
        self.assertFalse(self.send('grove', 'complete', id=pending['id'], answer=wrong)['correct'])
        self.assertFalse(self.send('grove', 'complete', id=pending['id'], answer=pending['answer'])['correct'])

    def test_typing_checks_text_accuracy_timing_and_only_game_input(self):
        self.assertEqual(self.send('typing', 'begin', lesson={})['error'], 'invalid_challenge')
        started = self.send('typing', 'begin', lesson='home')
        self.assertGreaterEqual(len(started['text']), 12)
        events = [{'key': char, 'ms': (i+1)*200} for i, char in enumerate(started['text'])]
        self.advance(len(events)*.2+2)
        for data in ([], [{'key': started['text'], 'ms': 2000}], events[:-1]):
            result = self.send('typing', 'complete', id=started['id'], events=data, correct=True, wpm=200)
            self.assertFalse(result['ok'])
        self.assertFalse(self.send('typing', 'complete', id=started['id'], events=[{**e, 'ms': 0} for e in events])['ok'])
        result = self.send('typing', 'complete', id=started['id'], events=events)
        self.assertTrue(result['correct'])
        started = self.send('typing', 'begin', lesson='words')
        keys = list('zzzzzzzzzz') + ['Backspace']*10 + list(started['text'])
        self.advance(len(keys)*.2+2)
        result = self.send('typing', 'complete', id=started['id'], events=[{'key': c, 'ms': (i+1)*200} for i,c in enumerate(keys)])
        self.assertTrue(result['ok']); self.assertFalse(result['correct'])
        self.assertEqual(result['reward_seconds'], 0)

    def test_old_pending_credits_are_retired_without_calling_any_transport(self):
        for module, service in self.host.services.items():
            state = deepcopy(service.account(self.uid))
            state['receipts'] = {
                'pending-platform': {'id': 'pending-platform', 'backend': 'platform', 'reward_seconds': None, 'reward_day': '2026-09-14'},
                'pending-legacy': {'id': 'pending-legacy', 'requested_seconds': 180, 'reward_seconds': None},
                'already-paid': {'id': 'already-paid', 'reward_seconds': 60}}
            if module == 'pawberry':
                state['receipt'] = state['receipts']['pending-legacy']
                state['counts']['add'] = 4
            service.persist(self.uid, state)
            service.accounts.clear()
        with patch('subprocess.run', side_effect=AssertionError('games must not call a time service')):
            self.host.refresh(self.now)
            for module, service in self.host.services.items():
                state = service.account(self.uid)
                self.assertEqual(state['receipts']['pending-platform']['reward_seconds'], 0)
                self.assertEqual(state['receipts']['pending-legacy']['reward_seconds'], 0)
                self.assertEqual(state['receipts']['already-paid']['reward_seconds'], 60)
                service.accounts.clear()
                self.host.refresh(self.now)
                self.assertTrue(self.send(module, 'status')['ok'])
            self.assertEqual(self.send('pawberry', 'status')['completed']['add'], 4)
            self.assertEqual(self.solve_pet(self.pawberry())['reward_seconds'], 0)

    def test_existing_pawberry_limits_and_work_survive_removing_saved_rewards(self):
        service = self.host.services['pawberry']
        for backend in ('legacy', 'platform'):
            limits = {'add': 5, 'subtract': 8, 'multiply': 2}
            config = {'users': {self.user: {**limits, 'screen_time': {'enabled': True, 'backend': backend}}}}
            storage.write_json(service.path, config)
            started = self.pawberry('multiply')
            state = service.account(self.uid); state['counts']['add'] = 4; service.persist(self.uid, state)
            self.host.services['pawberry'] = type(service)(self.host)
            service = self.host.services['pawberry']
            self.assertEqual(service.config['users'][self.user], limits)
            self.assertEqual(storage.read_json(service.path, {})['users'][self.user], limits)
            self.assertEqual(self.send('pawberry', 'status')['remaining']['add'], 1)
            result = self.solve_pet(started)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['reward_seconds'], 0)
            self.send('pawberry', 'users.set', peer=0, user=self.user, enabled=True)
            self.assertEqual(service.config['users'][self.user], limits)



class Packaging(unittest.TestCase):
    def test_fresh_game_module_selection_does_not_enable_a_clock(self):
        spec = importlib.util.spec_from_file_location('game_manage', ROOT/'service/manage.py')
        manage = importlib.util.module_from_spec(spec); spec.loader.exec_module(manage)
        for game in PROVIDERS:
            modules, selected = manage.selected_modules({}, game)
            self.assertEqual(modules, [game]); self.assertEqual(selected, {game})
        modules, _ = manage.selected_modules({'modules': ['school', 'time']}, 'typing')
        self.assertEqual(set(modules), {'school', 'time', 'typing', 'pawberry'})
        modules, _ = manage.selected_modules({'version': '3.0.0', 'modules': ['school', 'time']}, 'typing')
        self.assertNotIn('pawberry', modules, 'an explicitly removed module must stay removed')
        self.assertEqual(manage.config_path('pawberry').name, 'pawberry.json')

    @unittest.skipUnless((ROOT/'WorkSteps.js').exists(), 'Pawberry owns the arithmetic view')
    def test_python_verification_agrees_with_actual_javascript_working(self):
        rng = random.Random(371)
        problems = [{'a': 300, 'b': 156, 'operation': 'subtract'}]
        for op in ('add','subtract','multiply','divide'):
            for _ in range(500):
                a,b = rng.randrange(10,1000),rng.randrange(10,1000)
                if op == 'subtract': a,b = max(a,b),min(a,b)
                if op == 'divide': b=rng.randrange(2,10); a=b*rng.randrange(5,10)
                problems.append({'a':a,'b':b,'operation':op})
        problems += [{'a':a,'b':b,'operation':'multiply'} for a in range(1,10) for b in range(1,10)]
        script = "const fs=require('fs'),w=require('./WorkSteps.js');process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8')).map(p=>w.build(p.a,p.b,p.operation).steps.map(s=>({kind:s.kind,value:s.expected})))));"
        expected = json.loads(subprocess.check_output(['node','-e',script], input=json.dumps(problems).encode(), cwd=ROOT))
        for problem, steps in zip(problems, expected):
            self.assertEqual(work.expected_steps(problem), steps, problem)

if __name__ == '__main__':
    unittest.main()
