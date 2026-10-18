"""Narrow command transport into Harbor main; no host execution API."""
import asyncio
import json
import shlex


class ContainerBridge:
    def __init__(self, environment, audit_path, timeout_sec=300):
        self.environment = environment
        self.audit_path = audit_path
        self.timeout_sec = timeout_sec
        self.tasks = set()
        self.errors = []
        self.lock = asyncio.Lock()

    async def execute(self, request):
        if set(request) != {'command'} or not isinstance(request['command'], str) or not request['command'].strip():
            raise ValueError('Only a nonempty command is accepted; service, user, env and host paths are not configurable')
        # Both the process inside the container and the host transport are bounded.
        command = f'timeout --signal=TERM --kill-after=5 {self.timeout_sec} bash -lc {shlex.quote(request["command"])}'
        result = await self.environment.exec(command=command, cwd='/app', timeout_sec=self.timeout_sec + 10)
        return {'stdout': result.stdout or '', 'stderr': result.stderr or '', 'returnCode': result.return_code}

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            request = json.loads(await asyncio.wait_for(reader.readline(), 10))
            async with self.lock:
                with self.audit_path.open('a') as audit:
                    audit.write(json.dumps({'phase': 'start', **request}) + '\n')
                result = await self.execute(request)
                with self.audit_path.open('a') as audit:
                    audit.write(json.dumps({'phase': 'end', **result}) + '\n')
            writer.write((json.dumps(result) + '\n').encode())
            await writer.drain()
        except Exception as error:
            self.errors.append(str(error))
            writer.write((json.dumps({'error': f'Harbor container transport: {error}'}) + '\n').encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            self.tasks.discard(task)

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
