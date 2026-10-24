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
        self.assertTrue(all(r['executionState']=='completed' for r in issues))
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

    async def test_late_connection_after_shutdown_never_executes_a_command(self):
        await self.bridge.close()
        await self.call()
        self.environment.exec.assert_not_awaited()
        self.bridge.check_verification()

    async def test_shutdown_closes_accepted_socket_before_handler_first_step(self):
        reader=AsyncMock();writer=SimpleNamespace(close=Mock(),wait_closed=AsyncMock())
        task=self.bridge.handle(reader,writer)
        await self.bridge.close()
        self.assertTrue(task.cancelled())
        writer.close.assert_called()
        self.environment.exec.assert_not_awaited()
        self.assertFalse(self.bridge.tasks)

    async def test_agent_gate_archives_transport_receipt_and_allows_only_known_outcome(self):
        try:
            from src.execution.adapters.quantum_harbor.agent import DeepSeekHarborAgent
        except ModuleNotFoundError as error:
            if error.name.startswith('harbor'):
                self.skipTest('Harbor Python environment required for adapter integration')
            raise
        for scenario in ('reply_lost', 'exec_unknown', 'inflight'):
            fatal=scenario!='reply_lost'
            with self.subTest(scenario=scenario):
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
                entered=asyncio.Event();client=[]
                async def pending(**kwargs):
                    entered.set();await asyncio.Future()
                if scenario=='inflight':self.environment.exec.side_effect=pending
                async def create_worker(*args,**kwargs):
                    async def completed():
                        if scenario=='inflight':
                            reader,writer=await asyncio.open_unix_connection(args[4]);client.append(writer)
                            writer.write(b'{"command":"pending command"}\n');await writer.drain()
                            await asyncio.wait_for(entered.wait(),2)
                        else:await self.call(lost_reply=not fatal)
                        return 0
                    return SimpleNamespace(returncode=0,wait=completed)
                with patch('src.execution.adapters.quantum_harbor.agent.ContainerBridge', return_value=self.bridge), \
                     patch('src.execution.adapters.quantum_harbor.agent.asyncio.create_subprocess_exec', create_worker), \
                     patch('src.execution.adapters.quantum_harbor.agent.release'):
                    if fatal:
                        with self.assertRaisesRegex(RuntimeError, 'Container transport failed'):
                            await asyncio.wait_for(agent.run('fixture', self.environment, SimpleNamespace()),3)
                    else:
                        await agent.run('fixture', self.environment, SimpleNamespace())
                for writer in client:writer.close();await writer.wait_closed()
                receipt = json.loads((self.root / 'container-transport.json').read_text())
                self.assertEqual(receipt['verificationBlocked'], fatal)
                self.assertTrue(receipt['issues'])
