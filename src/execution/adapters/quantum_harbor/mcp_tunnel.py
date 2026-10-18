"""Forward native MCP HTTP bytes through main's network, without rewriting MCP."""
import asyncio
from urllib.parse import urlsplit, urlunsplit


# Runs inside main. No qsim filesystem, Docker socket, or host credentials enter it.
SOCKET_RELAY = '''import os, select, socket, sys
with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=15) as remote:
    remote.settimeout(None)
    while True:
        ready, _, _ = select.select([0, remote], [], [])
        if 0 in ready:
            data = os.read(0, 65536)
            if not data:
                break
            remote.sendall(data)
        if remote in ready:
            data = remote.recv(65536)
            if not data:
                break
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
'''


class McpTunnel:
    def __init__(self, main_container, endpoint):
        self.main_container = main_container
        self.endpoint = urlsplit(endpoint)
        if (self.endpoint.scheme != 'http' or not self.endpoint.hostname
                or self.endpoint.username or self.endpoint.password or self.endpoint.fragment):
            raise ValueError('Expected a task-provided HTTP MCP endpoint without credentials')
        self.server = None
        self.connections = set()
        self.errors = []

    async def start(self):
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0)
        port = self.server.sockets[0].getsockname()[1]
        return urlunsplit(('http', f'127.0.0.1:{port}', self.endpoint.path, self.endpoint.query, ''))

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.connections.add(task)
        proc = None
        pumps = []
        try:
            proc = await asyncio.create_subprocess_exec(
                'docker', 'exec', '-i', self.main_container, 'python3', '-u', '-c', SOCKET_RELAY,
                self.endpoint.hostname, str(self.endpoint.port or 80),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

            async def pump(source, destination):
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()

            pumps = [asyncio.create_task(pump(reader, proc.stdin)),
                     asyncio.create_task(pump(proc.stdout, writer))]
            done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
            for completed in done:
                completed.result()
        except (ConnectionError, OSError) as error:
            self.errors.append(str(error))
        finally:
            for pump_task in pumps:
                pump_task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            if proc:
                proc.stdin.close()
                try:
                    await asyncio.wait_for(proc.wait(), 3)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                diagnostic = (await proc.stderr.read()).decode(errors='replace').strip()
                if proc.returncode and diagnostic:
                    self.errors.append(diagnostic)
            writer.close()
            await writer.wait_closed()
            self.connections.discard(task)

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for task in list(self.connections):
            task.cancel()
        await asyncio.gather(*self.connections, return_exceptions=True)
