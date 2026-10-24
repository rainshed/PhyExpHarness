"""Narrow command transport into Harbor main; no host execution API."""
import asyncio
import json
import shlex
import time
import uuid


class InvalidCommand(ValueError):
    """A rejected tool invocation, returned to the Solver for correction."""


class ContainerBridge:
    def __init__(self, environment, audit_path, timeout_sec=300, *, deadline=None, clock=time.time):
        self.environment = environment
        self.audit_path = audit_path
        self.timeout_sec = timeout_sec
        self.deadline = deadline
        self.clock = clock
        self.tasks = set()
        self.issues = []
        self.lock = asyncio.Lock()

    async def execute(self, request):
        if not isinstance(request, dict) or set(request) != {'command'} or not isinstance(request['command'], str) or not request['command'].strip():
            raise InvalidCommand('Only a nonempty command is accepted; service, user, env and host paths are not configurable')
        # Both the process inside the container and the host transport are bounded.
        seconds = self.timeout_sec if self.deadline is None else self.deadline-self.clock()
        if seconds <= 0:raise TimeoutError('Benchmark agent deadline reached')
        command = f'timeout --signal=TERM --kill-after=5 {seconds} bash -lc {shlex.quote(request["command"])}'
        result = await self.environment.exec(command=command, cwd='/app', timeout_sec=seconds + 10)
        return {'stdout': result.stdout or '', 'stderr': result.stderr or '', 'returnCode': result.return_code}

    @property
    def errors(self):
        return [issue['message'] for issue in self.issues if issue['blocksVerification']]

    def diagnostics(self):
        return {'schemaVersion': 1, 'verificationBlocked': bool(self.errors), 'issues': self.issues}

    def check_verification(self):
        if self.errors:
            raise RuntimeError('Container transport failed: ' + '; '.join(self.errors))

    def audit(self, call_id, **data):
        with self.audit_path.open('a') as audit:
            audit.write(json.dumps({'callId': call_id, 'time': self.clock(), **data}) + '\n')

    def issue(self, call_id, stage, execution, error):
        # A lost reply cannot undo a recorded command result. An exec failure or
        # missing audit leaves the outcome uncertain even if a later call works.
        blocked = execution == 'running' or stage in ('audit_start', 'audit_end')
        self.issues.append({'callId': call_id, 'stage': stage, 'executionState': execution,
                            'blocksVerification': blocked, 'message': str(error),
                            'type': type(error).__name__, 'time': self.clock()})

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        call_id = uuid.uuid4().hex
        stage, execution = 'read_request', 'not_started'
        try:
            request = json.loads(await asyncio.wait_for(reader.readline(), 10))
            async with self.lock:
                stage = 'audit_start'
                self.audit(call_id, phase='start', **({'command': request.get('command')} if isinstance(request, dict) else {'request': request}))
                stage, execution = 'execute', 'running'
                result = await self.execute(request)
                execution, stage = 'completed', 'audit_end'
                self.audit(call_id, phase='end', **result)
            stage = 'deliver_response'
            writer.write((json.dumps(result) + '\n').encode())
            await writer.drain()
            for issue in self.issues:
                if not issue['blocksVerification'] and 'recoveredBy' not in issue:
                    issue['recoveredBy'] = call_id
        except InvalidCommand as error:
            execution = 'rejected'
            try:
                stage = 'audit_end'
                self.audit(call_id, phase='rejected', code='invalid_command')
                stage = 'deliver_response'
                writer.write((json.dumps({'error': f'Harbor container transport: {error}'}) + '\n').encode())
                await writer.drain()
            except Exception as delivery_error:
                self.issue(call_id, stage, execution, delivery_error)
        except asyncio.CancelledError as error:
            self.issue(call_id, stage, execution, error)
            raise
        except Exception as error:
            self.issue(call_id, stage, execution, error)
            try:
                writer.write((json.dumps({'error': f'Harbor container transport: {error}'}) + '\n').encode())
                await writer.drain()
            except Exception as delivery_error:
                self.issue(call_id, 'deliver_error', 'not_started', delivery_error)
        finally:
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), 1)
            except Exception as error:
                self.issue(call_id, 'close', 'not_started', error)
            finally:
                self.tasks.discard(task)

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
