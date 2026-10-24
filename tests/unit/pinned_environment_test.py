"""Guard the adapter's compose lifecycle without requiring Harbor or Docker."""
import asyncio
import importlib.util
import json
import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class ComposePolicyTests(unittest.TestCase):
    def setUp(self):
        calls = self.calls = []
        options = self.options = []
        class Docker:
            async def _run_docker_compose_command(self, command, *args, **kwargs):
                calls.append(command)
                options.append(kwargs)
                return 'ok'
        module = types.ModuleType('harbor.environments.docker.docker')
        module.DockerEnvironment = Docker
        path = Path(__file__).resolve().parents[2]/'src/execution/adapters/quantum_harbor/pinned_environment.py'
        spec = importlib.util.spec_from_file_location('fixture_pinned_environment', path)
        loaded = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'harbor.environments.docker.docker':module}):
            spec.loader.exec_module(loaded)
        self.env = object.__new__(loaded.PinnedDockerEnvironment)
        self.module = loaded
        self.env._startup_deadline = None

    def test_trial_never_builds_or_pulls_and_cleanup_keeps_images_but_removes_volumes(self):
        async def exercise():
            for command in [['build'],['pull']]:
                with self.assertRaises(ValueError): await self.env._run_docker_compose_command(command)
            await self.env._run_docker_compose_command(['up','--detach','--wait'])
            await self.env._run_docker_compose_command(['down','--rmi','local','--volumes','--remove-orphans'])
            with self.assertRaises(ValueError): await self.env.start(force_build=True)
        asyncio.run(exercise())
        self.assertEqual(self.calls, [['up','--detach','--wait','--no-build','--pull','never'],
                                     ['down','--volumes','--remove-orphans']])

    def test_compose_uses_remaining_task_budget_and_does_not_reset_for_each_command(self):
        self.env._startup_deadline = 610
        with patch.object(self.module.time, 'monotonic', return_value=110):
            asyncio.run(self.env._run_docker_compose_command(['up', '--detach', '--wait']))
        self.assertEqual(self.calls[-1][-2:], ['--wait-timeout', '500'])
        self.assertEqual(self.options[-1]['timeout_sec'], 500)
        with patch.object(self.module.time, 'monotonic', return_value=609):
            asyncio.run(self.env._run_docker_compose_command(['cp', 'source', 'main:/target']))
        self.assertEqual(self.options[-1]['timeout_sec'], 1)
        with patch.object(self.module.time, 'monotonic', return_value=611):
            with self.assertRaises(TimeoutError):
                asyncio.run(self.env._run_docker_compose_command(['up', '--detach', '--wait']))
        self.assertEqual(len(self.calls), 2)

    def test_failure_and_cancellation_are_archived_before_cleanup_without_masking_cause(self):
        with tempfile.TemporaryDirectory() as directory:
            self.env.trial_paths = types.SimpleNamespace(trial_dir=Path(directory))
            self.env._pin_role = 'agent'
            self.env._startup_budget_seconds = 600
            detail = {'code': 'environment_healthcheck_failed', 'phase': 'healthcheck',
                      'containers': [{'health': 'unhealthy'}]}
            for error in [RuntimeError('command failed\nPHYEXP_ENVIRONMENT_STARTUP='+json.dumps(detail)),
                          asyncio.CancelledError(), TimeoutError('expired')]:
                with patch.object(self.env, '_start_pinned', AsyncMock(side_effect=error)):
                    with self.assertRaises(type(error)):
                        asyncio.run(self.env.start())
                receipt = json.loads((Path(directory)/'phyexp/environment-startup-agent.json').read_text())
                expected = ('environment_start_interrupted' if isinstance(error, asyncio.CancelledError)
                            else 'environment_start_timeout' if isinstance(error, TimeoutError)
                            else 'environment_healthcheck_failed')
                self.assertEqual(receipt['code'], expected)
                self.assertEqual(receipt['budgetSeconds'], 600)
                self.assertIsNone(self.env._startup_deadline)
            with patch.object(self.env, '_start_pinned', AsyncMock()):
                asyncio.run(self.env.start())
            receipt = json.loads((Path(directory)/'phyexp/environment-startup-agent.json').read_text())
            self.assertEqual(receipt['status'], 'ready')
            self.assertNotIn('code', receipt)

    def test_last_streamed_health_survives_outer_timeout_and_preserves_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            self.env.trial_paths = types.SimpleNamespace(trial_dir=Path(directory))
            self.env._pin_role = 'agent'
            self.env._startup_budget_seconds = 600
            forwarded = AsyncMock()
            detail = {'code': None, 'phase': 'healthcheck', 'containers': [{'health': 'starting'}]}
            async def pending_start():
                await self.env._run_docker_compose_command(['up', '-d', '--wait'], on_output=forwarded)
                await self.options[-1]['on_output']('PHYEXP_ENVIRONMENT_STARTUP='+json.dumps(detail)+'\n', 'stdout')
                raise TimeoutError('outer deadline')
            with patch.object(self.env, '_start_pinned', pending_start):
                with self.assertRaises(TimeoutError):
                    asyncio.run(self.env.start())
            forwarded.assert_awaited_once()
            receipt = json.loads((Path(directory)/'phyexp/environment-startup-agent.json').read_text())
            self.assertEqual(receipt['code'], 'environment_start_timeout')
            self.assertEqual(receipt['compose']['containers'][0]['health'], 'starting')
