"""Harbor agent adapter: isolated DeepSeek loop, fixed host gateway, commands only in main."""
import asyncio
import json
import os
import re
import signal
import shlex
import tempfile
import time
import subprocess
from pathlib import Path

from harbor.agents.base import BaseAgent
from .bridge import ContainerBridge
from .mcp_tunnel import McpTunnel

from ...host.task_network import restrict_main, release
from ...host.task_time import start_solver_clock


class DeepSeekHarborAgent(BaseAgent):
    @staticmethod
    def name():
        return 'phyexp-deepseek-h0'

    def version(self):
        return '0.2.0'

    def __init__(self, *args, recipe_path=None, bundle_root=None, deadline=None, benchmark_time=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not bundle_root or not deadline:
            raise ValueError('Frozen bundle root and absolute deadline are required')
        self.bundle_root = Path(bundle_root).resolve()
        self.deadline = float(deadline)
        self.activity_deadline = self.deadline
        self.benchmark_time = benchmark_time
        self.recipe_path = self.bundle_root / 'recipe.json'
        self.recipe = json.loads(self.recipe_path.read_text())
        selected=self.recipe
        if os.environ.get('PHYEXP_REFERENCE_SPEC'):
            ref=json.loads(Path(os.environ['PHYEXP_REFERENCE_SPEC']).read_text())
            selected=(ref.get('native') or {}).get('call') or ref['fixedSolver']
        expected = f'{selected["provider"]}/{selected["model"]}'
        if self.model_name != expected:
            raise ValueError(f'Model must match the frozen recipe: {expected}')
        # Sibling of agent/, outside the model-writable /logs/agent mount.
        self.host_logs = self.logs_dir.parent / 'phyexp'
        self.host_logs.mkdir(parents=True, exist_ok=True)

    async def setup(self, environment):
        result = await environment.exec(command="command -v bash timeout python3 && python3 -c 'import mcp, numpy, scipy' && test ! -e /verifier/private && test ! -S /var/run/docker.sock", cwd='/app', timeout_sec=30)
        (self.host_logs / 'setup.json').write_text(json.dumps({'returnCode': result.return_code, 'stdout': result.stdout, 'stderr': result.stderr}, indent=2))
        if result.return_code != 0:
            raise RuntimeError('Task container prerequisites failed; see phyexp/setup.json')
        # Record the actual running image IDs, not only mutable image tags.
        project = environment.session_id.lower()
        if not re.match(r'^[a-z0-9]', project):
            project = '0' + project
        project = re.sub(r'[^a-z0-9_-]', '-', project)
        listing = await asyncio.create_subprocess_exec('docker', 'ps', '-q', '--filter',
            f'label=com.docker.compose.project={project}', stdout=asyncio.subprocess.PIPE)
        ids, _ = await listing.communicate()
        if listing.returncode != 0 or not ids.strip():
            raise RuntimeError('Cannot identify the running task containers')
        inspect = await asyncio.create_subprocess_exec('docker', 'inspect', *ids.decode().split(),
            '--format', '{{json .Name}} {{json .Image}}', stdout=asyncio.subprocess.PIPE)
        images, _ = await inspect.communicate()
        if inspect.returncode != 0:
            raise RuntimeError('Cannot record the running task image IDs')
        (self.host_logs / 'container-images.txt').write_bytes(images)
        main = await asyncio.create_subprocess_exec('docker', 'ps', '-q', '--filter',
            f'label=com.docker.compose.project={project}', '--filter',
            'label=com.docker.compose.service=main', stdout=asyncio.subprocess.PIPE)
        main_ids, _ = await main.communicate()
        if main.returncode != 0 or len(main_ids.decode().split()) != 1:
            raise RuntimeError('Expected exactly one main container for MCP transport')
        self.main_container = main_ids.decode().strip()
        qsim_ids = subprocess.check_output(['docker', 'ps', '-q', '--filter',
            f'label=com.docker.compose.project={project}', '--filter', 'label=com.docker.compose.service=qsim'], text=True).split()
        if len(qsim_ids) != 1:
            raise RuntimeError('Expected one qsim sidecar')
        self.qsim_container = qsim_ids[0]
        self.network = await asyncio.to_thread(restrict_main, self.main_container, self.qsim_container, os.environ.get('PHYEXP_LAUNCH_ID'))
        (self.host_logs / 'isolation.json').write_text(json.dumps({'main':self.main_container,
            'qsim':self.qsim_container, 'network':self.network, 'deadline':self.deadline,
            'agentSource':__file__, 'bundleRoot':str(self.bundle_root)}, indent=2))

    async def connect_mcp(self, environment, endpoints, tunnels):
        connections = []
        discovery = {}
        if not endpoints:
            raise RuntimeError('Harbor did not provide the required task MCP server')
        for endpoint in endpoints:
            if endpoint['transport'] != 'streamable-http':
                raise ValueError('This adapter supports task MCP over streamable HTTP')
            # Read-only discovery verifies the entire expected tool inventory;
            # it neither submits probes nor consumes the scientific budget.
            script = '''import asyncio, json, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def main():
    async with streamablehttp_client(sys.argv[1]) as (read, write, _):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            tools = []
            cursor = None
            while True:
                page = await session.list_tools(cursor=cursor)
                tools.extend(tool.model_dump(mode='json', exclude_none=True) for tool in page.tools)
                cursor = page.nextCursor
                if not cursor:
                    break
            print(json.dumps({'initialize': initialized.model_dump(mode='json', exclude_none=True), 'tools': tools}))
asyncio.run(main())
'''
            checked = await environment.exec(command='python3 -c ' + shlex.quote(script) + ' ' + shlex.quote(endpoint['url']),
                                             cwd='/app', timeout_sec=30)
            if checked.return_code != 0:
                raise RuntimeError('Task MCP discovery failed: ' + (checked.stderr or ''))
            discovered = json.loads(checked.stdout)
            if not discovered['tools']:
                raise RuntimeError('Task MCP server returned no tools')
            discovery[endpoint['name']] = discovered
            tunnel = McpTunnel(self.main_container, endpoint['url'])
            tunnels.append(tunnel)
            connections.append({**endpoint, 'url': await tunnel.start(),
                'toolNames': [tool['name'] for tool in discovered['tools']],
                'toolCallTimeoutMs': max(1, int((self.deadline-time.time())*1000)) if self.benchmark_time else self.recipe['commandTimeoutSec'] * 1000})
        (self.host_logs / 'mcp-discovery.json').write_text(json.dumps(discovery, indent=2))
        (self.host_logs / 'mcp-connections.json').write_text(json.dumps(connections, indent=2))

    async def run(self, instruction, environment, context):
        # Harbor's asyncio.wait_for begins immediately before calling run().
        # Mirror that phase for gateway/tool cancellation; Harbor remains the
        # authority and will also cancel this coroutine at its native deadline.
        if self.benchmark_time:
            timing=start_solver_clock(self.benchmark_time,self.activity_deadline,time.time())
            started=timing['solverStartedAt'];self.deadline=timing['solverDeadline']
            timing_path=self.host_logs/'timing.json'
            timing_path.with_suffix('.tmp').write_text(json.dumps(timing,indent=2))
            timing_path.with_suffix('.tmp').replace(timing_path)
        endpoints = [{'name': server.name, 'transport': server.transport, 'url': server.url} for server in self.mcp_servers]
        (self.host_logs / 'instruction.md').write_text(instruction)
        (self.host_logs / 'environment.json').write_text(json.dumps({'cwd': '/app', 'mcpServers': endpoints,
            **({'timing':timing} if self.benchmark_time else {})}, indent=2))
        bridge = ContainerBridge(environment, self.host_logs / 'container-exec.jsonl',
                                 self.recipe.get('commandTimeoutSec',300),deadline=self.deadline if self.benchmark_time else None)
        proc = None
        tunnels = []
        with tempfile.TemporaryDirectory(prefix='phyexp-bridge-', dir='/tmp') as temp:
            socket_path = str(Path(temp) / 'exec.sock')
            server = await asyncio.start_unix_server(bridge.handle, path=socket_path, limit=1024 * 1024)
            os.chmod(socket_path, 0o600)
            try:
                await self.connect_mcp(environment, endpoints, tunnels)
                with (self.host_logs / 'worker.log').open('w') as log:
                    proc = await asyncio.create_subprocess_exec(
                        'node', str(Path(__file__).parents[2]/'reference/dsh-worker.mjs' if os.environ.get('PHYEXP_REFERENCE_SPEC') else Path(__file__).with_name('worker.mjs')),
                        str(self.host_logs), str(self.bundle_root), socket_path, str(int(self.deadline * 1000)),
                        stdout=log, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
                    code = await proc.wait()
                if code != 0:
                    if self.benchmark_time and time.time() >= self.deadline:
                        from harbor.trial.errors import AgentTimeoutError
                        raise AgentTimeoutError('Benchmark agent deadline reached')
                    raise RuntimeError(f'DeepSeek worker exited {code}; see phyexp/runtime-summary.json')
                # Close admission and account for unfinished commands before the
                # verifier gate; connection cleanup must not hide late failures.
                server.close()
                await bridge.close()
                await server.wait_closed()
                bridge.check_verification()
            finally:
                if proc and proc.returncode is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), 10)
                    except asyncio.TimeoutError:
                        os.killpg(proc.pid, signal.SIGKILL)
                        await proc.wait()
                server.close()
                await bridge.close()
                await server.wait_closed()
                (self.host_logs / 'container-transport.json').write_text(json.dumps(bridge.diagnostics(), indent=2))
                for tunnel in tunnels:
                    await tunnel.close()
                (self.host_logs / 'mcp-transport.json').write_text(json.dumps({
                    'transport': 'native-streamable-http-via-main-tcp',
                    'errors': [error for tunnel in tunnels for error in tunnel.errors]}, indent=2))
                self.populate_context_post_run(context)
                # Archive the solver's scripts and working files before Harbor tears down main.
                try:
                    await environment.download_dir('/app', self.host_logs / 'workspace')
                finally:
                    await asyncio.to_thread(release, self.network, self.main_container, self.qsim_container)

    def populate_context_post_run(self, context):
        summary_path = self.host_logs / 'runtime-summary.json'
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            usage = summary.get('usage', {})
            context.n_input_tokens = usage.get('promptTokens')
            context.n_output_tokens = usage.get('outputTokens')
            context.n_cache_tokens = usage.get('cacheReadTokens')
            context.cost_usd = None  # Subscription usage is not an API dollar bill.
            context.metadata = summary
