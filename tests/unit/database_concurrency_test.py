import concurrent.futures
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.control.database import begin_write
from src.control.stop_review import StopRuntime
from src.control.store import Store, Refused
from src.reporting.reports import Reports, render


class DatabaseConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'control.sqlite')
        model = {'provider': 'openai-codex', 'model': 'gpt-6-sol', 'reasoningEffort': 'medium'}
        config = {'solver': model, 'meta': model, 'tasks': ['time_budgeted_hamlearn_10q'],
                  'concurrency': 15, 'wallTimeSeconds': 3600, 'modelAccessPolicy': 'control-only-v1'}
        self.c = self.store.create(config, 'fixture')['id']
        self.store.control(self.c, 'start', 'start')
        self.reports = Reports(self.store, self.root)
        self.analysis = {'summary': 'Fixture', 'observations': [], 'hypotheses': [],
                         'limitations': [], 'decision': 'Continue', 'evidenceRefs': []}
        self.facts = self.reports.facts(self.c)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, **kwargs):
        return self.reports.save(self.c, self.analysis, facts=self.facts, **kwargs)

    def test_render_does_not_block_another_writer(self):
        entered, release = threading.Event(), threading.Event()
        def slow_render(record):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test renderer blocked')
            return render(record)
        with concurrent.futures.ThreadPoolExecutor() as pool, patch('src.reporting.reports.render', slow_render):
            report = pool.submit(self.save)
            self.assertTrue(entered.wait(3))
            try:
                candidate = pool.submit(self.store.candidate, self.c, {'id': 'fixture', 'path': '/fixture', 'plugins': []}, 'H0')
                self.assertEqual(candidate.result(timeout=2)['description'], 'H0')
            finally:
                release.set()
            row = report.result(timeout=5)
        self.assertEqual(json.loads(Path(row['markdownPath']).with_name('report.json').read_text()), row)

    def test_fifteen_concurrent_freezes_queries_and_reports_keep_revisions_and_identity(self):
        self.facts['fixturePayload'] = 'x' * (512 * 1024)
        barrier = threading.Barrier(15)
        def work(i):
            barrier.wait(timeout=5)
            candidate = self.store.candidate(self.c, {'id': f'bundle-{i}', 'path': '/fixture', 'plugins': []}, f'H{i}')
            self.store.status(self.c)
            row = self.save(meta_request={'requestId': f'request-{i % 5}', 'payload': str(i % 5)})
            return candidate, row
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as pool:
            results = list(pool.map(work, range(15)))
        reports = self.store.list('reports', self.c)
        self.assertEqual(len({c['id'] for c, _ in results}), 15)
        self.assertEqual(len(reports), 5)
        self.assertEqual(sorted(r['analysisRevision'] for r in reports), list(range(1, 6)))
        for i in range(5):
            self.assertEqual(len({r['id'] for _, r in results if r['metaRequest']['requestId'] == f'request-{i}'}), 1)
        self.assertEqual(len([e for e in self.store.events(self.c) if e['type'] == 'report_saved']), 5)

    def test_revision_conflict_rechecked_after_render(self):
        entered, release = threading.Event(), threading.Event()
        original = render
        def pause_first(record):
            if threading.current_thread().name.startswith('first'):
                entered.set()
                release.wait(5)
            return original(record)
        with concurrent.futures.ThreadPoolExecutor(thread_name_prefix='first') as pool, patch('src.reporting.reports.render', pause_first):
            first = pool.submit(self.save, expected_revision=0)
            self.assertTrue(entered.wait(3))
            try:
                winner = self.save(expected_revision=0)
            finally:
                release.set()
            with self.assertRaisesRegex(Refused, 'revision changed'):
                first.result(timeout=3)
        self.assertEqual([r['id'] for r in self.store.list('reports', self.c)], [winner['id']])

    def test_publish_failure_rolls_back_and_same_request_can_be_saved(self):
        request = {'requestId': 'same', 'payload': 'payload'}
        with patch('src.reporting.reports.os.replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.save(meta_request=request)
        self.assertEqual(self.store.list('reports', self.c), [])
        row = self.save(meta_request=request)
        self.assertEqual(self.save(meta_request=request)['id'], row['id'])
        self.assertTrue(Path(row['markdownPath']).is_file())

    def test_runtime_read_call_proceeds_while_another_connection_holds_writer(self):
        c = self.store.get('campaigns', self.c)
        c['config'].update(stopPolicy='goal-or-budget-v1', metaComposition={'version': 'meta-composition-v2'})
        self.store.put('campaigns', c)
        self.store.put('meta_sessions', {'id': 'session', 'campaignId': self.c, 'state': 'running',
                                        'agents': {'main': {'preset': 'phyexp-meta'}}})
        runtime = StopRuntime(SimpleNamespace(store=self.store, meta_api=SimpleNamespace(call=lambda *args: self.store.status(self.c))))
        with concurrent.futures.ThreadPoolExecutor() as pool, self.store.connection(True):
            future = pool.submit(runtime.dispatch, 'session', 'call', {'agentId': 'main', 'operation': 'campaign_status'})
            self.assertEqual(future.result(timeout=2)['id'], self.c)

    def test_lock_retry_is_bounded_and_never_repeats_transaction_body(self):
        blocker = sqlite3.connect(self.store.path)
        blocker.execute('BEGIN IMMEDIATE')
        try:
            db = sqlite3.connect(self.store.path)
            started = time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                begin_write(db, timeout=.1)
            self.assertLess(time.monotonic() - started, 1)
            db.close()
        finally:
            blocker.rollback()
            blocker.close()
        calls = 0
        with self.assertLogs('phyexp.control.database', level='WARNING') as logs:
            with self.assertRaises(sqlite3.OperationalError):
                with self.store.connection(True, operation='test.rollback') as db:
                    calls += 1
                    db.execute("INSERT INTO events(campaign,data) VALUES(?,?)", (self.c, '{}'))
                    raise sqlite3.OperationalError('database is locked private-payload')
        self.assertEqual(calls, 1)
        self.assertNotIn('private-payload', ''.join(logs.output))
        self.assertIn('test.rollback', ''.join(logs.output))
        self.assertFalse(any(e.get('type') is None for e in self.store.events(self.c)))
