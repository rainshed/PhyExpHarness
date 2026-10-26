"""Installation failures, retry behavior and diagnostics before dependencies exist."""
import argparse
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.onboarding import cli, common, install


class InstallationTests(unittest.TestCase):
    def test_missing_prerequisites_are_structured_and_do_not_install(self):
        failure = {'id': 'python', 'status': 'failed', 'detail': '3.12', 'nextStep': 'install 3.13'}
        with patch.object(install, 'runtime_checks', return_value=[failure]), patch.object(install.subprocess, 'run') as run:
            self.assertEqual(install.setup()['checks'], [failure])
            run.assert_not_called()

    def test_setup_reuses_dependencies_but_rebuilds_and_only_receipts_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'.venv/bin').mkdir(parents=True); (root/'.venv/bin/python').touch()
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                return subprocess.CompletedProcess(command, 0)
            with patch.object(install, 'runtime_checks', return_value=[]), patch.object(install, 'installed', return_value=(True, 'ok')), \
                 patch.object(install, 'probe', return_value=subprocess.CompletedProcess([], 0, '3.13\n', '')), \
                 patch.object(install, 'lock_fingerprint', return_value='locked'), patch.object(install.subprocess, 'run', side_effect=run):
                result = install.setup(root)
                self.assertTrue(result['reusedDependencies'])
                self.assertEqual([c[-2:] for c in commands], [['pip', 'check'], ['run', 'build']])
                self.assertEqual(common.read_json(root/'.runtime/setup.json')['fingerprint'], 'locked')
                commands.clear()
                install.setup(root, repair=True)
                self.assertIn(['npm', 'ci'], commands)
                self.assertTrue(any('--require-hashes' in c for c in commands))
            (root/'.runtime/setup.json').unlink()
            with patch.object(install, 'runtime_checks', return_value=[]), patch.object(install, 'installed', return_value=(False, 'missing')), \
                 patch.object(install, 'probe', return_value=subprocess.CompletedProcess([], 0, '3.13\n', '')), \
                 patch.object(install.subprocess, 'run', return_value=subprocess.CompletedProcess([], 9)):
                with self.assertRaisesRegex(common.Problem, '安装步骤失败'):
                    install.setup(root)
                self.assertFalse((root/'.runtime/setup.json').exists())

    def test_doctor_handles_missing_docker_and_missing_harbor_without_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(install, 'runtime_checks', return_value=[]), patch.object(install, 'installed', return_value=(False, 'missing')), \
                 patch.object(install, 'probe', return_value=subprocess.CompletedProcess([], 127, '', 'not found')):
                result = install.doctor({'data_dir': tmp, 'quantum_harbor': str(root/'missing')}, root=root)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['modelRequests'], 0)
            failed = {r['id'] for r in result['checks'] if r['status'] == 'failed'}
            self.assertTrue({'docker', 'quantum_harbor', 'dependencies', 'build'} <= failed)
            self.assertFalse(any(r['id'].startswith('image:') for r in result['checks']))

    def test_explicit_settings_override_saved_and_environment_without_reading_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            common.write_json(root/'onboarding/local.json', {'control_port': 18002, 'ui_port': 18001, 'quantum_harbor': '/saved'})
            with patch.dict('os.environ', {'PHYEXP_QUANTUM_HARBOR': '/environment', 'PHYEXP_CONTROL_URL': '', 'PHYEXP_UI_PORT': ''}):
                result = common.settings(argparse.Namespace(data_dir=tmp, quantum_harbor='/explicit', control_port=19002))
            self.assertEqual(result['control_port'], 19002)
            self.assertEqual(result['ui_port'], 18001)
            self.assertEqual(result['quantum_harbor'], '/explicit')

    def test_remote_control_url_never_receives_local_token(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'PHYEXP_CONTROL_URL': 'https://example.com'}):
            with self.assertRaisesRegex(common.Problem, '回环'):
                common.settings(argparse.Namespace(data_dir=tmp))

    def test_cli_json_failure_has_stable_status_and_action(self):
        out = io.StringIO()
        with patch.object(cli, 'doctor', return_value={'status': 'failed', 'checks': []}), \
             patch.object(cli, 'settings', return_value={}), contextlib.redirect_stdout(out):
            code = cli.main(['doctor', '--project-only', '--json'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue()), {'schemaVersion': 1, 'command': 'doctor', 'status': 'failed', 'checks': []})


if __name__ == '__main__':
    unittest.main()
