import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('project_scope', ROOT/'scripts/check-boundaries.py')
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class ProjectScopeTests(unittest.TestCase):
    def test_standard_dependencies_and_generic_contracts_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'src').mkdir()
            (root/'src/runtime.py').write_text("import sqlite3\ncommand = ['docker', 'inspect']\n")
            (root/'README.md').write_text('Docker/Harbor, local evidence and external HTTPS configuration.')
            self.assertEqual(scope.project_violations(root), [])

    def test_deployment_code_config_assets_and_docs_are_rejected(self):
        cases = {
            'src/control/storage.py': 'from src.evidence.cold import ColdArchive',
            'scripts/container.sh': 'podman network create --internal example',
            'profiles/storage.json': '{"file":"archive-policy.json"}',
            'src/execution/process-assets.json': '{"src/execution/host/container_runtime.py":"runtime.py"}',
            'docs/operations/host.md': 'TensorTrain2 release /var/tmp/phyexp-user/releases/current',
            'templates/standalone/README.md': 'Run tailscale serve to access the application.',
        }
        for name, content in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                file = root/name
                file.parent.mkdir(parents=True)
                file.write_text(content)
                self.assertTrue(any(name in error for error in scope.project_violations(root)))

    def test_empty_deployment_modules_are_rejected_but_generated_sdk_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated = root/'knowledge/plugin-sdk/reference/runtime.md'
            generated.parent.mkdir(parents=True)
            generated.write_text('Third-party SDK mentions NFS and Podman.')
            self.assertEqual(scope.project_violations(root), [])
            removed = root/'src/evidence/cold.py'
            removed.parent.mkdir(parents=True)
            removed.touch()
            self.assertTrue(any('deployment-only file' in error for error in scope.project_violations(root)))
