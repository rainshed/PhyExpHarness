"""Real local subprocesses; no model calls, task containers or scientific outcomes."""
import json
import os
import select
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from src.control.meta import MetaDriver
from src.control.service import ControlService
from src.execution.adapters.quantum_harbor.results import archive_manifest

ROOT = Path(__file__).resolve().parents[2]


class ProcessLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.service = ControlService(ROOT, self.data, ROOT.parent / 'Quantum-Harbor', 'http://127.0.0.1:1')
        self.store = self.service.store
        config = {
            'solver': {'provider': 'openai-codex', 'model': 'gpt-6-sol', 'reasoningEffort': 'medium'},
            'meta': {'provider': 'openai-codex', 'model': 'gpt-6-astra', 'reasoningEffort': 'medium'},
            'tasks': ['time_budgeted_hamlearn_10q'], 'maxRounds': 10, 'maxTrials': 10,
            'concurrency': 1, 'wallTimeSeconds': 7200, 'trialTimeSeconds': 3600,
            'softTokenLimit': 3000000, 'reserveSeconds': 900, 'reserveTokens': 300000,
        }
        self.campaign = self.store.create(config, 'fixture')['id']
        self.store.control(self.campaign, 'start', 'start')
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=3)
            process.stdin.close()
            process.stdout.close()
        self.service.pool.shutdown(wait=True)
        self.temp.cleanup()

    def child(self):
        process = subprocess.Popen(
            [sys.executable, '-c', 'import sys; print("ready", flush=True); sys.stdin.readline()'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.processes.append(process)
        self.assertTrue(select.select([process.stdout], [], [], 3)[0])
        self.assertEqual(process.stdout.readline(), 'ready\n')
        return process

    def exit_child(self, process):
        process.stdin.write('\n')
        process.stdin.flush()
        self.assertTrue(select.select([process.stdout], [], [], 3)[0])
        self.assertEqual(process.stdout.read(), '')
        # Do not wait()/poll() here: the service must perform the actual OS reap.

    def assert_reaped(self, process):
        deadline = time.monotonic() + 3
        while process.returncode is None and time.monotonic() < deadline:
            self.service.tick()
            time.sleep(.01)
        self.assertEqual(process.returncode, 0)
        with self.assertRaises(ChildProcessError):
            os.waitpid(process.pid, os.WNOHANG)

    def trial(self, scored=False):
        candidate = self.store.candidate(self.campaign, {'id': 'fixture', 'path': '/fixture', 'plugins': []},
                                         'Fixture', check={'status': 'passed'})
        self.store.submit(self.campaign, candidate['id'], ['time_budgeted_hamlearn_10q'], 1,
                          'fixture-' + str(len(self.processes)))
        trial = self.store.claim(self.campaign)
        output = self.data / trial['id']
        output.mkdir()
        summary = {'fixture': True, 'status': 'completed' if scored else 'infrastructure_error',
                   'pipelineStatus': 'completed' if scored else 'failed',
                   'officialReward': 0 if scored else None, 'usage': {}, 'wallTimeSeconds': 0,
                   'stopReason': None if scored else 'fixture_failure',
                   'scoringStatus': 'completed' if scored else 'not_run'}
        (output / 'summary.json').write_text(json.dumps(summary))
        archive_manifest(output)
        process = self.child()
        trial = self.store.trial_update(trial['id'], state='running', output=str(output), pid=process.pid)
        self.service.children[trial['id']] = process
        return trial, process, output

    def test_trial_exit_is_reaped_and_terminal_result_is_unchanged(self):
        for scored in [True, False]:
            with self.subTest(scored=scored):
                trial, process, output = self.trial(scored)
                original = {p.name: p.read_bytes() for p in output.iterdir()}
                self.exit_child(process)
                self.assert_reaped(process)
                self.service.tick()
                result = self.store.get('trials', trial['id'])
                self.assertEqual(result['state'], 'finished' if scored else 'failed')
                self.assertEqual(result['score'], 0 if scored else None)
                self.assertNotIn(trial['id'], self.service.children)
                events = self.store.events(self.campaign)
                self.service.tick()
                self.assertEqual(self.store.get('trials', trial['id']), result)
                self.assertEqual(self.store.events(self.campaign), events)
                self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, original)

    def test_archived_trial_keeps_live_process_until_exit_even_after_campaign_finishes(self):
        trial, process, _ = self.trial()
        self.service.tick()
        self.assertEqual(self.store.get('trials', trial['id'])['state'], 'failed')
        self.store.finalize(self.campaign)
        # A live child waiting on stdin must not block or be terminated by a tick.
        self.service.tick()
        self.assertIsNone(process.returncode)
        self.assertIn(trial['id'], self.service.children)
        self.exit_child(process)
        self.assert_reaped(process)
        self.assertNotIn(trial['id'], self.service.children)

    def test_collection_failure_keeps_reaped_handle_for_retry(self):
        trial, process, output = self.trial()
        file = output / 'summary.json'
        original = file.read_bytes()
        file.write_text('broken archive')
        self.exit_child(process)
        self.assert_reaped(process)
        result = self.store.get('trials', trial['id'])
        self.assertEqual(result['state'], 'running')
        self.assertIn('Archive', result['lastCollectionError'])
        self.assertIs(self.service.children[trial['id']], process)
        file.write_bytes(original)
        self.service.tick()
        self.service.tick()
        result = self.store.get('trials', trial['id'])
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['stopReason'], 'fixture_failure')
        self.assertNotIn(trial['id'], self.service.children)
        self.assertEqual(len([e for e in self.store.events(self.campaign) if e['type'] == 'trial_finished']), 1)

    def test_meta_collection_failure_keeps_handle_then_releases_after_retry(self):
        driver = MetaDriver(self.service)
        self.service.meta_driver = driver
        output = self.data / 'meta'
        output.mkdir()
        file = output / 'summary.json'
        file.write_text('invalid json')
        process = self.child()
        self.store.put('meta_sessions', {'id': 'meta-fixture', 'campaignId': self.campaign,
                       'state': 'running', 'output': str(output), 'pid': process.pid, 'leaseId': 'fixture'})
        driver.children['meta-fixture'] = process
        self.exit_child(process)
        deadline = time.monotonic() + 3
        while True:
            try:
                self.service.tick()
            except json.JSONDecodeError:
                break
            self.assertLess(time.monotonic(), deadline, 'Meta collection did not reach the invalid summary')
            time.sleep(.01)
        self.assertEqual(process.returncode, 0)
        with self.assertRaises(ChildProcessError):
            os.waitpid(process.pid, os.WNOHANG)
        self.assertIn('meta-fixture', driver.children)
        file.write_text(json.dumps({'status': 'completed'}))
        self.service.tick()
        self.assertEqual(self.store.get('meta_sessions', 'meta-fixture')['state'], 'completed')
        self.assertEqual(self.store.get('campaigns', self.campaign)['state'], 'finished')
        self.service.tick()
        self.assertNotIn('meta-fixture', driver.children)

    def test_terminal_meta_processes_are_reaped_even_when_campaign_is_finished(self):
        driver = MetaDriver(self.service)
        self.service.meta_driver = driver
        self.store.finalize(self.campaign)
        for state in ['completed', 'failed', 'interrupted']:
            with self.subTest(state=state):
                process = self.child()
                row = self.store.put('meta_sessions', {'id': state, 'campaignId': self.campaign,
                                     'state': state, 'pid': process.pid})
                driver.children[state] = process
                self.exit_child(process)
                self.assert_reaped(process)
                self.assertNotIn(state, driver.children)
                self.assertEqual(self.store.get('meta_sessions', state), row)

    def test_reconnected_service_does_not_reap_an_unowned_child(self):
        trial, process, _ = self.trial()
        self.service.tick()
        self.store.finalize(self.campaign)
        restarted = ControlService(ROOT, self.data, ROOT.parent / 'Quantum-Harbor', 'http://127.0.0.1:1')
        try:
            self.exit_child(process)
            restarted.tick()
            self.assertIsNone(process.returncode)
            # The owning service still has to collect the OS exit status.
            self.assert_reaped(process)
            self.assertNotIn(trial['id'], self.service.children)
        finally:
            restarted.pool.shutdown(wait=True)
