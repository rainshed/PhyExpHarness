import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.execution.adapters.quantum_harbor.bridge import ContainerBridge


class BridgeRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(
            stdout='{"accepted":true}', stderr='', return_code=0)), download_dir=AsyncMock())
        self.bridge = ContainerBridge(self.environment, self.root / 'container-exec.jsonl')

    async def call(self, *, lost_reply=False, lost_close=False, request=None):
        reader = AsyncMock()
        reader.readline.return_value = json.dumps(request or {'command': 'submit fixture'}).encode() + b'\n'
        writer = SimpleNamespace(write=Mock(), drain=AsyncMock(side_effect=ConnectionError('Connection lost') if lost_reply else None),
                                 close=Mock(), wait_closed=AsyncMock(side_effect=ConnectionError('Connection lost') if lost_close else None))
        await self.bridge.handle(reader, writer)

    async def test_recorded_result_and_lost_reply_allow_verification_after_recovery(self):
        await self.call(lost_reply=True, lost_close=True)
        await self.call()
        self.bridge.check_verification()
        self.assertEqual(self.environment.exec.await_count, 2)  # no hidden command retry
        self.assertFalse(self.bridge.tasks)
        issues = self.bridge.diagnostics()['issues']
        self.assertTrue(issues)
        self.assertTrue(all(not r['blocksVerification'] and r.get('recoveredBy') for r in issues))
        records = [json.loads(line) for line in self.bridge.audit_path.read_text().splitlines()]
        self.assertEqual([r['phase'] for r in records], ['start', 'end', 'start', 'end'])
        self.assertEqual(records[0]['callId'], records[1]['callId'])

    async def test_unknown_command_outcome_remains_fatal_after_another_success(self):
        self.environment.exec.side_effect = [ConnectionError('exec connection lost'), SimpleNamespace(stdout='ok', stderr='', return_code=0)]
        await self.call()
        await self.call()
        with self.assertRaisesRegex(RuntimeError, 'exec connection lost'):
            self.bridge.check_verification()
        issue = self.bridge.diagnostics()['issues'][0]
        self.assertEqual(issue['executionState'], 'running')
        self.assertNotIn('recoveredBy', issue)

    async def test_audit_failure_blocks_verification_even_with_command_result(self):
        audit = self.bridge.audit
        def failing_audit(call_id, **data):
            if data['phase'] == 'end':
                raise OSError('audit disk unavailable')
            audit(call_id, **data)
        with patch.object(self.bridge, 'audit', failing_audit):
            await self.call()
        with self.assertRaisesRegex(RuntimeError, 'audit disk unavailable'):
            self.bridge.check_verification()
        self.assertEqual(self.bridge.issues[0]['stage'], 'audit_end')

    async def test_cancelling_inflight_command_is_accounted_for_before_verifier_gate(self):
        entered = asyncio.Event()
        async def pending(**kwargs):
            entered.set()
            await asyncio.Future()
        self.environment.exec.side_effect = pending
        task = asyncio.create_task(self.call())
        await asyncio.wait_for(entered.wait(), 2)
        await self.bridge.close()
        self.assertTrue(task.cancelled())
        self.assertFalse(self.bridge.tasks)
        with self.assertRaises(RuntimeError):
            self.bridge.check_verification()

    async def test_invalid_command_and_failed_error_reply_do_not_fake_execution_failure(self):
        await self.call(request={'command': 'true', 'phase': 'injected', 'call_id': 'injected'}, lost_reply=True)
        self.environment.exec.assert_not_awaited()
        self.bridge.check_verification()
        self.assertEqual(self.bridge.issues[0]['executionState'], 'rejected')

    async def test_agent_gate_archives_transport_receipt_and_allows_only_known_outcome(self):
        try:
            from src.execution.adapters.quantum_harbor.agent import DeepSeekHarborAgent
        except ModuleNotFoundError as error:
            if error.name.startswith('harbor'):
                self.skipTest('Harbor Python environment required for adapter integration')
            raise
        for fatal in (False, True):
            with self.subTest(fatal=fatal):
                self.bridge = ContainerBridge(self.environment, self.root / 'container-exec.jsonl')
                self.environment.exec.side_effect = ConnectionError('exec unknown') if fatal else None
                agent = object.__new__(DeepSeekHarborAgent)
                agent.host_logs = self.root
                agent.bundle_root = self.root
                agent.deadline = time.time() + 60
                agent.benchmark_time = None
                agent.recipe = {}
                agent.mcp_servers = []
                agent.network = 'fixture'
                agent.main_container = 'main'
                agent.qsim_container = 'qsim'
                agent.connect_mcp = AsyncMock()
                async def completed():
                    await self.call(lost_reply=not fatal)
                    return 0
                process = SimpleNamespace(returncode=0, wait=completed)
                with patch('src.execution.adapters.quantum_harbor.agent.ContainerBridge', return_value=self.bridge), \
                     patch('src.execution.adapters.quantum_harbor.agent.asyncio.create_subprocess_exec', AsyncMock(return_value=process)), \
                     patch('src.execution.adapters.quantum_harbor.agent.release'):
                    if fatal:
                        with self.assertRaisesRegex(RuntimeError, 'exec unknown'):
                            await agent.run('fixture', self.environment, SimpleNamespace())
                    else:
                        await agent.run('fixture', self.environment, SimpleNamespace())
                receipt = json.loads((self.root / 'container-transport.json').read_text())
                self.assertEqual(receipt['verificationBlocked'], fatal)
                self.assertTrue(receipt['issues'])
