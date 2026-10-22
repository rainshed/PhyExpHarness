import copy
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.control.service import ControlService
from src.control.server import make_app

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('model_fixture', ROOT / 'tests/fixtures/model_provider.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
BASE = {'solver': {'provider': 'openai-codex', 'model': 'gpt-6-sol', 'reasoningEffort': 'medium'},
        'meta': {'provider': 'openai-codex', 'model': 'gpt-6-astra', 'reasoningEffort': 'medium'},
        'tasks': ['time_budgeted_hamlearn_10q'], 'concurrency': 1, 'wallTimeSeconds': 7200}


class ProviderSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.remote = fixture.server()
        self.thread = threading.Thread(target=self.remote.serve_forever, daemon=True)
        self.thread.start()
        self.service = ControlService(ROOT, self.data, ROOT.parent/'Quantum-Harbor', 'http://127.0.0.1:1')
        self.client = TestClient(make_app(self.service, supervise=False))
        self.client.headers['Authorization'] = 'Bearer '+self.service.user_token
        self.route = {'adapter': 'pi-ai', 'api': 'openai-completions', 'baseURL': f'http://127.0.0.1:{self.remote.server_port}/v1',
                      'auth': {'type': 'api-key', 'env': 'PHYEXP_PROVIDER_FIXTURE_API_KEY'},
                      'models': [{'id': 'fixture-model', 'reasoningEfforts': False, 'maxTokens': 1024, 'contextWindow': 16000}]}

    def tearDown(self):
        self.service.pool.shutdown(wait=True)
        self.client.close()
        self.remote.shutdown()
        self.remote.server_close()
        self.temp.cleanup()

    def save(self, **changes):
        body = {'id': 'fixture', 'name': '离线测试网关', 'route': self.route, 'enabled': True,
                'expectedRevision': self.client.get('/providers').json()['revision'], **changes}
        return self.client.post('/providers/save', json=body)

    def test_atomic_settings_credentials_restart_and_secret_free_reads(self):
        before = self.client.get('/providers').json()['revision']
        response = self.save(apiKey=fixture.KEY)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(fixture.KEY, response.text)
        self.assertEqual(response.json()['revision'], before+1)
        p = response.json()['providers'][-1]
        self.assertTrue(p['credential']['saved'])
        self.assertNotIn(fixture.KEY, self.client.get('/models').text)
        self.assertEqual(self.service.providers.path.stat().st_mode & 0o777, 0o600)
        with self.service.providers.connection() as db:
            self.assertNotIn(fixture.KEY, db.execute('SELECT data FROM settings').fetchone()['data'])
        other = ControlService(ROOT, self.data, ROOT.parent/'Quantum-Harbor', 'http://127.0.0.1:1')
        try:
            self.assertEqual(other.store.model_config['providers']['fixture'], self.route)
            self.assertEqual(other.providers.environment('fixture', self.route)[self.route['auth']['env']], fixture.KEY)
        finally:
            other.pool.shutdown(wait=True)
        # Invalid config + replacement key must commit neither half.
        failed = self.save(route={**self.route, 'api': 'invalid'}, apiKey='replacement')
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(self.service.providers.environment('fixture', self.route)[self.route['auth']['env']], fixture.KEY)

    def test_conflicts_and_authority(self):
        revision = self.client.get('/providers').json()['revision']
        def save(i):
            try:
                return self.service.providers.save({'id': 'fixture', 'name': 'Name '+str(i), 'route': self.route, 'expectedRevision': revision})
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(r is not None for r in pool.map(save, range(2))), 1)
        c = self.service.store.create(BASE, 'fixture')
        for role in ['meta', 'solver']:
            _, token = self.service.lease(c['id'], role, time.time()+60)
            self.client.headers['Authorization'] = 'Bearer '+token
            for endpoint in ['/providers', '/provider-tests/missing', '/models']:
                self.assertEqual(self.client.get(endpoint).status_code, 403)
            for endpoint in ['/providers/save', '/providers/fixture/test', '/providers/fixture/credential/remove']:
                self.assertEqual(self.client.post(endpoint, json={}).status_code, 403)

    def test_frozen_routes_replays_disable_and_credential_deletion(self):
        self.assertEqual(self.save(apiKey=fixture.KEY).status_code, 200)
        config = {**BASE, 'solver': {'provider': 'fixture', 'model': 'fixture-model'}}
        original = self.service.store.create(config, 'original')
        snapshot = copy.deepcopy(original['config'])
        with patch.dict(os.environ, {self.route['auth']['env']: 'environment-key'}):
            self.assertEqual(self.service.providers.environment('fixture', self.route)[self.route['auth']['env']], fixture.KEY)
        changed = {**self.route, 'baseURL': 'https://new.invalid/v1', 'models': [{'id': 'new-model', 'reasoningEfforts': False}]}
        self.assertEqual(self.save(route=changed, enabled=False).status_code, 200)
        self.assertFalse(any(m['provider']=='fixture' for m in self.client.get('/models').json()['models']))
        self.assertEqual(self.service.store.create(config, 'original'), original)
        self.assertEqual(self.service.store.get('campaigns', original['id'])['config'], snapshot)
        limits = self.service.store.control(original['id'], 'limits', 'update', changes={'wallTimeSeconds': 7500})
        self.assertEqual(limits['config']['modelRoutes'], snapshot['modelRoutes'])
        # The selected credential is passed to old frozen workers without modifying their recipe.
        self.assertEqual(self.service.providers.environment('fixture', snapshot['modelRoutes']['solver'])[self.route['auth']['env']], fixture.KEY)
        revision = self.client.get('/providers').json()['revision']
        self.assertEqual(self.client.post('/providers/fixture/credential/remove', json={'expectedRevision': revision}).status_code, 403)
        c = self.service.store.get('campaigns', original['id'])
        c['state'] = 'finished'
        self.service.store.put('campaigns', c)
        with patch.dict(os.environ, {self.route['auth']['env']: 'environment-key'}):
            response = self.client.post('/providers/fixture/credential/remove', json={'expectedRevision': revision})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['providers'][-1]['credential']['source'], 'environment')
            self.assertEqual(self.service.providers.environment('fixture', self.route)[self.route['auth']['env']], 'environment-key')

    def wait_test(self, id):
        deadline = time.monotonic()+15
        while time.monotonic()<deadline:
            result = self.client.get('/provider-tests/'+id).json()
            if result['state']!='running':
                return result
            time.sleep(.05)
        self.fail('Probe did not finish')

    def test_live_loopback_protocols_test_usage_and_idempotency(self):
        for api in ['openai-completions', 'openai-responses', 'anthropic-messages']:
            route = {**self.route, 'api': api}
            if api=='anthropic-messages':route['baseURL']=route['baseURL'].removesuffix('/v1')
            saved = self.save(route=route, apiKey=fixture.KEY)
            body = {'model': 'fixture-model', 'expectedRevision': saved.json()['revision'], 'idempotencyKey': api}
            accepted = self.client.post('/providers/fixture/test', json=body)
            self.assertEqual(accepted.status_code, 200, accepted.text)
            result = self.wait_test(accepted.json()['id'])
            self.assertEqual(result['state'], 'passed', result)
            self.assertEqual(result['confirmedTokens'], 24)
            self.assertTrue(all(result['checks'].values()))
            calls = len(self.remote.calls)
            replay = self.client.post('/providers/fixture/test', json=body)
            self.assertEqual(replay.json()['id'], result['id'])
            self.assertEqual(len(self.remote.calls), calls)
            self.assertNotIn(fixture.KEY, json.dumps(result))
        self.assertEqual(len(self.remote.calls), 6)

    def test_failed_auth_redacted_and_missing_usage_not_zero(self):
        saved = self.save(apiKey='bad-private-fixture-key')
        result = self.wait_test(self.client.post('/providers/fixture/test', json={'model': 'fixture-model', 'expectedRevision': saved.json()['revision'], 'idempotencyKey': 'auth-failure'}).json()['id'])
        self.assertEqual(result['state'], 'failed')
        self.assertNotIn('bad-private-fixture-key', json.dumps(result))
        self.assertEqual(len(self.remote.calls), 1)
        self.assertEqual(result['usageStatus'], 'unknown')
        route = copy.deepcopy(self.route)
        route['models'][0]['id'] = 'no-usage'
        saved = self.save(route=route, apiKey=fixture.KEY)
        result = self.wait_test(self.client.post('/providers/fixture/test', json={'model': 'no-usage', 'expectedRevision': saved.json()['revision'], 'idempotencyKey': 'missing-usage'}).json()['id'])
        self.assertEqual(result['state'], 'failed', result)
        self.assertEqual(result['usageStatus'], 'unknown')
        self.assertIsNone(result['confirmedTokens'])

    def test_codex_route_and_process_environment_cannot_be_repurposed(self):
        codex = self.client.get('/providers').json()['providers'][0]['route']
        self.assertEqual(self.save(id='openai-codex', route={**codex, 'baseURL': 'https://other.invalid'}).status_code, 400)
        self.assertEqual(self.save(id='openai-codex', route=codex, apiKey=fixture.KEY).status_code, 400)
        for ref in ['NODE_OPTIONS', 'PHYEXP_CONTROL_URL', 'PATH']:
            route = {**self.route, 'auth': {'type': 'api-key', 'env': ref}}
            self.assertEqual(self.save(route=route, apiKey=fixture.KEY).status_code, 400)

    def test_database_failure_rolls_back_both_credential_and_configuration(self):
        import sqlite3
        self.save(apiKey=fixture.KEY)
        revision = self.service.providers.snapshot()['revision']
        with self.service.providers.connection(True) as db:
            db.execute("CREATE TRIGGER fail_save BEFORE UPDATE ON settings BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.service.providers.save({'id': 'fixture', 'name': 'Should roll back', 'route': self.route,
                                         'apiKey': 'replacement-secret', 'expectedRevision': revision})
        self.assertEqual(self.service.providers.snapshot()['revision'], revision)
        self.assertEqual(self.service.providers.environment('fixture', self.route)[self.route['auth']['env']], fixture.KEY)

    def test_stored_keys_reach_only_selected_host_role_and_never_frozen_context(self):
        from src.control.meta import MetaDriver
        from src.execution.bundle.freeze import freeze
        self.save(apiKey='solver-fixture-secret')
        self.save(id='meta-fixture', apiKey='meta-fixture-secret')
        config = {**BASE, 'solver': {'provider': 'fixture', 'model': 'fixture-model'},
                  'meta': {'provider': 'meta-fixture', 'model': 'fixture-model'}}
        campaign = self.service.store.create(config, 'hosts')
        original = copy.deepcopy(campaign['config'])
        recipe = json.loads((ROOT/'recipes/h0-sol.json').read_text())
        recipe.update(provider='fixture', model='fixture-model', providerConfig=self.route)
        recipe.pop('reasoningEffort', None)
        bundle = freeze(ROOT, self.data/'bundles', recipe)
        candidate = self.service.store.candidate(campaign['id'], bundle, 'fixture', check={'status': 'passed'})
        self.service.store.control(campaign['id'], 'start', 'start')
        self.service.store.submit(campaign['id'], candidate['id'], config['tasks'], 1, 'submit')
        trial = self.service.store.claim(campaign['id'])
        self.save(enabled=False, route={**self.route, 'baseURL': 'https://new.invalid'})
        runtime = self.data/'shared-runtime'
        with patch('src.control.service.prepare_runtime',return_value=runtime), patch('src.control.service.subprocess.Popen') as spawn:
            spawn.return_value.pid = 987654
            self.service._launch(trial)
            env = spawn.call_args.kwargs['env']
            self.assertEqual(env[self.route['auth']['env']], 'solver-fixture-secret')
            self.assertNotIn('meta-fixture-secret', env.values())
            argv=spawn.call_args.args[0]
            self.assertEqual(argv[1],str(runtime/'run.py'))
            self.assertEqual(argv[argv.index('--bundle')+1],bundle['path'])
            self.assertEqual(self.service.store.get('trials',trial['id'])['executionEntry'],str(runtime/'run.py'))
        driver = MetaDriver(self.service)
        with patch('src.control.meta.startup_context', return_value={'fixture': True}), patch('src.control.meta.subprocess.Popen') as spawn:
            spawn.return_value.pid = 987655
            driver.start(campaign['id'])
            env = spawn.call_args.kwargs['env']
            self.assertEqual(env[self.route['auth']['env']], 'meta-fixture-secret')
            self.assertNotIn('solver-fixture-secret', env.values())
        context = next((self.data/'campaigns'/campaign['id']/'meta-sessions').glob('*/context.json')).read_text()
        self.assertNotIn('fixture-secret', context)
        self.assertEqual(json.loads(context)['providerConfig'], original['modelRoutes']['meta'])
        frozen = (Path(bundle['path'])/'recipe.json').read_text()
        self.assertNotIn('fixture-secret', frozen)
        self.assertEqual(json.loads(frozen)['providerConfig'], original['modelRoutes']['solver'])

    def test_recovery_marks_interrupted_tests_unknown_and_does_not_retry(self):
        with self.service.providers.connection(True) as db:
            db.execute('INSERT INTO tests VALUES(?,?,?,?)', ('lost-test', 'lost-command', '{}', json.dumps({'id': 'lost-test', 'provider': 'fixture', 'state': 'running'})))
        other = ControlService(ROOT, self.data, ROOT.parent/'Quantum-Harbor', 'http://127.0.0.1:1')
        try:
            recovered = other.providers.get_test('lost-test')
            self.assertEqual(recovered['state'], 'interrupted')
            self.assertEqual(recovered['usageStatus'], 'unknown')
            self.assertEqual(len(self.remote.calls), 0)
        finally:
            other.pool.shutdown(wait=True)
