"""Model-free MCP preflight using the original Harbor Docker environment."""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.task import Task
from harbor.models.trial.paths import TrialPaths

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.integrations.quantum_harbor.agent import DeepSeekHarborAgent


async def main():
    task = Task(ROOT.parent / 'Quantum-Harbor/harbor_tasks/time_budgeted_hamlearn_10q')
    run_id = 'phyexp-mcp-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    paths = TrialPaths(ROOT / 'runs/smoke' / run_id)
    paths.mkdir()
    environment = DockerEnvironment(environment_dir=task.paths.environment_dir, environment_name=task.name,
        session_id=run_id.lower(), trial_paths=paths, task_env_config=task.config.environment)
    agent = DeepSeekHarborAgent(logs_dir=paths.agent_dir, model_name='openai-codex/gpt-6-sol',
                               mcp_servers=task.config.environment.mcp_servers)
    tunnels = []
    try:
        await environment.start(force_build=False)
        await agent.setup(environment)
        endpoints = [{'name': server.name, 'transport': server.transport, 'url': server.url}
                     for server in agent.mcp_servers]
        await agent.connect_mcp(environment, endpoints, tunnels)
        proc = await asyncio.create_subprocess_exec('node', str(Path(__file__).with_suffix('.mjs')),
                                                   str(agent.host_logs), cwd=ROOT)
        if await proc.wait() != 0:
            raise RuntimeError(f'MCP preflight failed; see {agent.host_logs}')
        print(f'Preflight archive: {paths.trial_dir}')
    finally:
        for tunnel in tunnels:
            await tunnel.close()
        (agent.host_logs / 'mcp-transport.json').write_text(json.dumps({
            'errors': [error for tunnel in tunnels for error in tunnel.errors]}, indent=2))
        await environment.stop(delete=True)


if __name__ == '__main__':
    asyncio.run(main())
