import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.integrations.quantum_harbor import batch
from src.integrations.quantum_harbor.results import archive_manifest, verify_manifest
from src.integrations.quantum_harbor.run import source_hashes, write_json


class BatchTests(unittest.TestCase):
    def test_failed_trial_is_archived_once_and_does_not_replace_or_skip_next_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'recipes').mkdir()
            (root / 'experiments').mkdir()
            (root / 'runs/h0').mkdir(parents=True)
            (root / 'reports/h0').mkdir(parents=True)
            recipe = {'model': 'gpt-6-sol'}
            write_json(root / 'recipes/h0.json', recipe)
            plan = {'id': 'batch-test', 'recipe': 'recipes/h0.json', 'tasks': ['a', 'b'],
                    'attempts': 1, 'retries': 0, 'purpose': 'test'}
            plan_path = root / 'experiments/batch.json'
            write_json(plan_path, plan)
            for task in plan['tasks']:
                folder = root / 'quantum/harbor_tasks' / task
                folder.mkdir(parents=True)
                (folder / 'task.toml').write_text('')
            called = []

            def execute(args, **kwargs):
                experiment = json.loads(Path(args[args.index('--experiment') + 1]).read_text())
                called.append(experiment['task'])
                run = root / 'runs/h0' / (experiment['id'] + '-attempt1')
                run.mkdir()
                reward = 0 if experiment['task'] == 'a' else 1
                write_json(run / 'summary.json', {'status': 'incomplete' if reward == 0 else 'completed',
                    'officialReward': reward, 'pipelineStatus': 'completed',
                    'taskOutcome': 'invalid_submission' if reward == 0 else 'passed'})
                write_json(run / 'provenance.json', {'recipe': recipe,
                    'harnessSourceHashes': source_hashes(root, ['src', 'recipes', 'experiments', 'package-lock.json']),
                    'harnessSourceUnchangedDuringRun': True, 'quantumSourceUnchangedDuringRun': True})
                archive_manifest(run)
                return SimpleNamespace(returncode=1-reward)

            with patch.object(batch, 'ROOT', root), patch.object(batch.subprocess, 'run', execute), \
                 patch('sys.argv', ['batch', '--experiment', str(plan_path), '--quantum-harbor', str(root / 'quantum'), '--data-dir', str(root)]):
                self.assertEqual(batch.main(), 0)
            self.assertEqual(called, ['a', 'b'])
            result = json.loads(next((root / 'runs/batches').glob('*/batch.json')).read_text())
            self.assertEqual([run['officialReward'] for run in result['runs']], [0, 1])
            self.assertEqual(result['officiallyGradedTasks'], 2)
            self.assertTrue(all(run['wallTimeSeconds'] >= 0 for run in result['runs']))
            self.assertGreater(verify_manifest(next((root / 'runs/batches').iterdir())), 0)
