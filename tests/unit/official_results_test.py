import json
import tempfile
import unittest
from pathlib import Path
from src.execution.adapters.quantum_harbor.official import collect
from src.execution.adapters.quantum_harbor.results import archive_manifest, collect as legacy


class OfficialResultsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for path, value in {
            'provenance.json': {'bundleId': 'candidate', 'task': 'task', 'recipe': {'model': 'solver'}},
            'harbor/result.json': {'stats': {'n_completed_trials': 1, 'n_errored_trials': 1}},
            'harbor/trial/result.json': {'task_name': 'task', 'trial_name': 'trial',
                'exception_info': {'exception_type': 'NonZeroAgentExitCodeError'},
                'verifier_result': {'rewards': {'reward': 1}}},
            'harbor/trial/lock.json': {'task': {'digest': 'task-digest'}},
            'harbor/trial/verifier/artifacts/score_report.json': {'task_id': 'task', 'reward': 1,
                'result': {'binary_pass': True}},
            'harbor/trial/verifier/artifacts/final_answer.json': {},
            'harbor/trial/phyexp/runtime-summary.json': {'status': 'nonzero_exit', 'exitCode': 7,
                'toolCalls': 0, 'bundleId': 'candidate'},
        }.items():
            p = self.root / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(value))
        (self.root / 'harbor/trial/verifier/reward.txt').write_text('1')

    def test_nonzero_and_missing_diagnostics_preserve_official_score(self):
        with self.assertRaises(ValueError): legacy(self.root)
        result = collect(self.root, bundle_id='candidate', task='task')
        self.assertEqual(result['officialReward'], 1)
        self.assertEqual(result['execution']['exitCode'], 7)
        self.assertEqual(result['evidenceStatus']['status'], 'partial')

    def test_archive_diagnostic_corruption_is_separate_from_official_tampering(self):
        archive_manifest(self.root)
        runtime = self.root / 'harbor/trial/phyexp/runtime-summary.json'
        runtime.write_text('truncated')
        self.assertEqual(collect(self.root, archived=True)['officialReward'], 1)
        (self.root / 'harbor/trial/verifier/reward.txt').write_text('0')
        with self.assertRaisesRegex(ValueError, 'Official evidence changed'):
            collect(self.root, archived=True)

    def test_identity_and_official_consistency(self):
        with self.assertRaisesRegex(ValueError, 'another candidate'): collect(self.root, bundle_id='other')
        with self.assertRaisesRegex(ValueError, 'another task'): collect(self.root, task='other')
        (self.root / 'harbor/trial/verifier/reward.txt').write_text('0')
        with self.assertRaises(ValueError): collect(self.root)

    def test_recollection_is_idempotent_and_does_not_rewrite_sources(self):
        archive_manifest(self.root)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(collect(self.root, archived=True), collect(self.root, archived=True))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_official_zero_without_submission_does_not_require_tool_execution(self):
        (self.root / 'harbor/trial/verifier/artifacts/final_answer.json').unlink()
        (self.root / 'harbor/trial/verifier/reward.txt').write_text('0')
        p = self.root / 'harbor/trial/result.json'; t = json.loads(p.read_text())
        t['verifier_result']['rewards']['reward'] = 0; p.write_text(json.dumps(t))
        (self.root / 'harbor/trial/verifier/artifacts/score_report.json').write_text(json.dumps(
            {'task_id': 'task', 'reward': 0, 'result': None}))
        result = collect(self.root)
        self.assertEqual(result['officialReward'], 0)
        self.assertEqual(result['taskOutcome'], 'no_submission')

    def test_absent_reward_keeps_execution_failure_and_verifier_source(self):
        from src.execution.adapters.quantum_harbor.official import unavailable
        reward=self.root/'harbor/trial/verifier/reward.txt'; reward.unlink()
        try: collect(self.root)
        except FileNotFoundError as error: result=unavailable(self.root,error,bundle_id='candidate',task='task')
        self.assertEqual(result['execution']['status'],'nonzero_exit')
        self.assertEqual(result['execution']['exitCode'],7)
        self.assertEqual(result['execution']['exception']['exception_type'],'NonZeroAgentExitCodeError')
        self.assertIsNone(result['officialReward'])
        self.assertEqual(result['officialResult']['status'],'unavailable')
