"""Harbor test agent for container/MCP/scoring compatibility, without a model."""
import asyncio
import json
from pathlib import Path
import shlex
import subprocess

from harbor.agents.base import BaseAgent
from src.execution.host.task_network import restrict_main, release


class PublicTaskProbeAgent(BaseAgent):
    @staticmethod
    def name(): return 'phyexp-public-task-compatibility-probe'

    def version(self): return '1.0.0'

    def __init__(self, *args, task, **kwargs):
        super().__init__(*args, **kwargs)
        self.task = task

    async def setup(self, environment):
        await environment.upload_file(Path(__file__).with_name('public_task_probe_client.py'), '/tmp/phyexp-task-probe.py')

    async def run(self, instruction, environment, context):
        evidence = self.logs_dir.parent/'phyexp'
        evidence.mkdir(exist_ok=True)
        resources = json.loads((evidence/'pinned-resources-agent.json').read_text())
        main, qsim = (resources[role]['container'] for role in ['main','qsim'])
        network = await asyncio.to_thread(restrict_main, main, qsim, self.session_id)
        try:
            inspected = json.loads(subprocess.check_output(['docker','inspect',main,qsim], text=True))
            # Keep proof of the configured boundaries without container env/secrets.
            receipt = [{'name':item['Name'],'image':item['Image'],
                'mounts':item['Mounts'],'hostConfig':{key:item['HostConfig'].get(key) for key in
                ['CapDrop','SecurityOpt','Memory','CpuQuota','CpuPeriod','PidsLimit','Privileged']},
                'networks':list(item['NetworkSettings']['Networks'])} for item in inspected]
            (evidence/'probe-containers.json').write_text(json.dumps(receipt, indent=2))
            result = await environment.exec(command='python3 /tmp/phyexp-task-probe.py '+shlex.quote(self.task), timeout_sec=540)
            (evidence/'probe-client.json').write_text(json.dumps({'returnCode':result.return_code,
                'stdout':result.stdout,'stderr':result.stderr}, indent=2))
            if result.return_code:
                raise RuntimeError('Public task probe failed; see phyexp/probe-client.json')
            (evidence/'probe-result.json').write_text(json.dumps(json.loads(result.stdout), indent=2))
        finally:
            await asyncio.to_thread(release, network, main, qsim)
