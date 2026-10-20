"""Guard the adapter's compose lifecycle without requiring Harbor or Docker."""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class ComposePolicyTests(unittest.TestCase):
    def setUp(self):
        calls = self.calls = []
        class Docker:
            async def _run_docker_compose_command(self, command, *args, **kwargs):
                calls.append(command)
                return 'ok'
        module = types.ModuleType('harbor.environments.docker.docker')
        module.DockerEnvironment = Docker
        path = Path(__file__).resolve().parents[2]/'src/execution/adapters/quantum_harbor/pinned_environment.py'
        spec = importlib.util.spec_from_file_location('fixture_pinned_environment', path)
        loaded = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'harbor.environments.docker.docker':module}):
            spec.loader.exec_module(loaded)
        self.env = object.__new__(loaded.PinnedDockerEnvironment)

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
