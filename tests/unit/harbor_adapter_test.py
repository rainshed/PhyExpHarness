import asyncio
import json
import tempfile
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.integrations.quantum_harbor.bridge import ContainerBridge
from src.integrations.quantum_harbor.results import archive_manifest, collect, verify_manifest
from src.integrations.quantum_harbor.mcp_tunnel import McpTunnel


class McpTunnelTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_binary_round_trip_and_cleanup_through_fixed_main(self):
        async def echo(reader, writer):
            try:
                while chunk := await reader.read(65536):
                    writer.write(chunk)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        upstream = await asyncio.start_server(echo, '127.0.0.1', 0)
        port = upstream.sockets[0].getsockname()[1]
        tunnel = McpTunnel('main-for-this-trial', f'http://127.0.0.1:{port}/mcp')
        create = asyncio.create_subprocess_exec
        children = []

        async def local_relay(*args, **kwargs):
            self.assertEqual(args[:6], ('docker', 'exec', '-i', 'main-for-this-trial', 'python3', '-u'))
            proc = await create(sys.executable, '-u', *args[6:], **kwargs)
            children.append(proc)
            return proc

        try:
            with patch('src.integrations.quantum_harbor.mcp_tunnel.asyncio.create_subprocess_exec', local_relay):
                from urllib.parse import urlsplit
                endpoint = urlsplit(await tunnel.start())
                reader, writer = await asyncio.open_connection(endpoint.hostname, endpoint.port)
                payload = bytes(range(256)) * 1000
                writer.write(payload)
                await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.readexactly(len(payload)), 5), payload)
                writer.close()
                await writer.wait_closed()
                await tunnel.close()
            self.assertEqual(tunnel.errors, [])
            self.assertTrue(children)
            self.assertTrue(all(proc.returncode == 0 for proc in children))
        finally:
            await tunnel.close()
            upstream.close()
            await upstream.wait_closed()

    def test_rejects_unhandled_transport_and_credentials(self):
        for endpoint in ['https://qsim:8123/mcp', 'http://user:secret@qsim/mcp', 'file:///tmp/mcp']:
            with self.assertRaises(ValueError):
                McpTunnel('main', endpoint)


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_main_container_exec_and_literal_command(self):
        environment = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(stdout='ok', stderr='', return_code=0)))
        bridge = ContainerBridge(environment, None)
        command = "python3 - <<'PY'\nprint('a; $(not-a-host-command)')\nPY"
        result = await bridge.execute({'command': command})
        import shlex
        kwargs = environment.exec.call_args.kwargs
        self.assertEqual(shlex.split(kwargs['command'])[-1], command)
        self.assertEqual(kwargs['cwd'], '/app')
        self.assertEqual(set(kwargs), {'command', 'cwd', 'timeout_sec'})
        self.assertEqual(result['returnCode'], 0)

    async def test_cannot_request_sidecar_user_or_host_environment(self):
        environment = SimpleNamespace(exec=AsyncMock())
        bridge = ContainerBridge(environment, None)
        for key in ['service', 'user', 'env', 'cwd']:
            with self.assertRaises(ValueError):
                await bridge.execute({'command': 'true', key: 'forbidden'})
        environment.exec.assert_not_called()


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'harbor/trial'
        self.write('harbor/result.json', {'stats': {'n_completed_trials': 1, 'n_errored_trials': 0}})
        self.write('harbor/trial/result.json', {'task_name': 'task', 'trial_name': 'trial',
            'exception_info': None, 'verifier_result': {'rewards': {'reward': 0}}})
        self.write('harbor/trial/lock.json', {'task': {'digest': 'sha256:test'}})
        self.write('harbor/trial/phyexp/runtime-summary.json', {'status': 'completed', 'toolCalls': 2,
            'recipe': {'id': 'h0'}, 'model': 'gpt-6-luna', 'provider': 'openai-codex'})
        self.write('harbor/trial/phyexp/events.json', [{'type': 'assistant/message', 'data': {'usage': {
            'inputTokens': 10, 'outputTokens': 3, 'cacheReadTokens': 20, 'totalTokens': 33}}}])
        self.write('harbor/trial/verifier/artifacts/score_report.json', {'task_id': 'task',
            'reward_binary': 0, 'result': {'binary_pass': False}})
        self.write('harbor/trial/verifier/artifacts/final_answer.json', {'answer': {'estimate': []}})
        (self.base / 'verifier/reward.txt').write_text('0\n')
        (self.base / 'verifier/artifacts/experiment_log.jsonl').write_text('{"event":"probe"}\n')

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def test_real_zero_is_completed_scientific_failure(self):
        result = collect(self.root)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['officialReward'], 0)
        self.assertFalse(result['sciencePassed'])

    def test_other_released_report_formats_preserve_official_verdicts(self):
        reports = [
            {'reward_binary': 0, 'passed': False, 'disposition': 'scored', 'metrics': {}},
            {'reward': 0, 'passed': False, 'disposition': 'scored'},
            {'passed': False, 'checks': {'gate': False}, 'metrics': {}},
            {'reward': 0, 'admission_checks': {'energy': False}},
        ]
        for report in reports:
            with self.subTest(report=report):
                self.write('harbor/trial/verifier/artifacts/score_report.json', {'task_id': 'task', **report})
                result = collect(self.root)
                self.assertEqual(result['taskOutcome'], 'failed_science')
                self.assertEqual(result['officialReward'], 0)
                self.assertEqual(result['score'], {'task_id': 'task', **report})

    def test_top_level_passed_cannot_disagree_with_reward(self):
        self.write('harbor/trial/verifier/artifacts/score_report.json', {
            'task_id': 'task', 'reward': 0, 'passed': True, 'disposition': 'scored'})
        with self.assertRaisesRegex(ValueError, 'disagree'):
            collect(self.root)

    def test_official_pre_scoring_rejections_are_not_infrastructure_errors(self):
        for report in [{'passed': False, 'reason': 'unscoreable'},
                       {'reward': 0, 'penalties': ['invalid final answer']},
                       {'reward': 0, 'passed': False, 'disposition': 'model_failure'}]:
            with self.subTest(report=report):
                self.write('harbor/trial/verifier/artifacts/score_report.json', {'task_id': 'task', **report})
                self.assertEqual(collect(self.root)['taskOutcome'], 'invalid_submission')

    def test_missing_reward_is_never_zero(self):
        (self.base / 'verifier/reward.txt').unlink()
        with self.assertRaises(FileNotFoundError):
            collect(self.root)

    def test_disagreeing_official_artifacts_fail(self):
        (self.base / 'verifier/reward.txt').write_text('1')
        with self.assertRaisesRegex(ValueError, 'disagree'):
            collect(self.root)

    def test_missing_submission_is_not_completed_h0(self):
        (self.base / 'verifier/artifacts/final_answer.json').unlink()
        self.assertEqual(collect(self.root)['status'], 'incomplete')

    def test_invalid_submission_retains_official_zero_and_completed_pipeline(self):
        self.write('harbor/trial/verifier/artifacts/score_report.json', {'task_id': 'task',
            'reward_binary': 0, 'result': None, 'penalties': ['invalid answer']})
        result = collect(self.root)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['pipelineStatus'], 'completed')
        self.assertEqual(result['taskOutcome'], 'invalid_submission')
        self.assertEqual(result['usage']['promptTokens'], 30)
        self.assertEqual(result['usage']['totalTokens'], 33)

    def test_infrastructure_exception_is_not_a_model_failure(self):
        self.write('harbor/trial/result.json', {'exception_info': {'exception_type': 'VerifierTimeoutError'}})
        with self.assertRaisesRegex(ValueError, 'exception'):
            collect(self.root)

    def test_wrong_task_report_fails(self):
        self.write('harbor/trial/verifier/artifacts/score_report.json', {'task_id': 'other', 'reward_binary': 0})
        with self.assertRaisesRegex(ValueError, 'another task'):
            collect(self.root)

    def test_archive_check_detects_changed_evidence(self):
        archive_manifest(self.root)
        self.assertGreater(verify_manifest(self.root), 0)
        (self.base / 'verifier/reward.txt').write_text('1\n')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            verify_manifest(self.root)

    def test_passing_reward_without_assessment_is_corrupt(self):
        (self.base / 'verifier/reward.txt').write_text('1')
        self.write('harbor/trial/result.json', {'task_name': 'task', 'trial_name': 'trial',
            'exception_info': None, 'verifier_result': {'rewards': {'reward': 1}}})
        self.write('harbor/trial/verifier/artifacts/score_report.json', {'task_id': 'task', 'reward_binary': 1, 'result': None})
        with self.assertRaisesRegex(ValueError, 'requires a submission and scientific assessment'):
            collect(self.root)


if __name__ == '__main__':
    unittest.main()
