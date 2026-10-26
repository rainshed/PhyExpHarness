"""Owned-process recovery and authenticated readiness; no global processes touched."""
import json
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.onboarding import api, runtime
from src.onboarding.common import Problem, write_json


class RuntimeTests(unittest.TestCase):
    def config(self, directory):
        quantum = Path(directory)/'quantum'; (quantum/'harbor_tasks').mkdir(parents=True, exist_ok=True)
        return {'source': '/source', 'data_dir': directory, 'quantum_harbor': str(quantum), 'model_config': None,
                'control_port': 18002, 'ui_port': 18001, 'control_url': 'http://127.0.0.1:18002', 'ui_url': 'http://127.0.0.1:18001'}

    def test_identity_must_match_source_data_and_quantum(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            health = {'service': 'independent-control', 'instance': {'source': '/source', 'dataDir': tmp, 'quantumHarbor': config['quantum_harbor']}}
            self.assertTrue(api.health_matches(health, config))
            self.assertFalse(api.health_matches(health, {**config, 'source': '/another'}))
            self.assertFalse(api.health_matches({'service': 'independent-control'}, config))

    def test_api_refuses_redirect_without_forwarding_token(self):
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(302); self.send_header('Location', '/stolen'); self.end_headers()
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp)/'user-token').write_text('fixture-secret')
                client = api.API({'data_dir': tmp, 'control_url': f'http://127.0.0.1:{server.server_port}'})
                with self.assertRaises(Problem) as error: client.request('/health')
                self.assertEqual(error.exception.code, 'http_302')
                self.assertNotIn('fixture-secret', str(error.exception))
                self.assertEqual(hits, ['/health'])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_occupied_control_port_never_spawns_or_kills(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            with patch.object(runtime, 'doctor', return_value={'status': 'passed'}), patch.object(runtime, 'port_open', return_value=True), \
                 patch.object(runtime.API, 'request', return_value={'service': 'different'}), patch.object(runtime, 'launch') as launch:
                with self.assertRaises(Problem) as error: runtime.start(config)
                self.assertEqual(error.exception.code, 'control_port_busy'); launch.assert_not_called()

    def test_repeat_start_reuses_matching_processes_and_keeps_login_out_of_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            state = {'config': config, 'control': {'pid': 101, 'identity': 'control'}, 'ui': {'pid': 102, 'identity': 'ui'}}
            write_json(Path(tmp)/'onboarding/processes.json', state)
            health = {'service': 'independent-control', 'instance': {'source': '/source', 'dataDir': tmp, 'quantumHarbor': config['quantum_harbor']}}
            with patch.object(runtime, 'doctor', return_value={'status': 'passed'}), patch.object(runtime, 'port_open', return_value=True), \
                 patch.object(runtime, 'alive', return_value=True), patch.object(runtime.API, 'request', return_value=health), \
                 patch.object(runtime, 'ui_ready', return_value=True), patch.object(runtime, 'login_url', return_value='http://127.0.0.1:18001/?token=secret'), \
                 patch.object(runtime, 'launch') as launch:
                result = runtime.start(config)
            launch.assert_not_called(); self.assertEqual(result['status'], 'passed')
            self.assertNotIn('secret', json.dumps(result))
            self.assertIn('#phyexp', (Path(tmp)/'onboarding/login.html').read_text())

    def test_stop_refuses_active_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            write_json(Path(tmp)/'onboarding/processes.json', {'config': config, 'control': {'pid': 99}})
            with patch.object(runtime, 'alive', return_value=True), patch.object(runtime.API, 'request', return_value=[{'state': 'running'}]), patch.object(runtime.os, 'kill') as kill:
                with self.assertRaises(Problem) as error: runtime.stop_local(config)
                self.assertEqual(error.exception.code, 'active_campaigns'); kill.assert_not_called()


if __name__ == '__main__': unittest.main()
