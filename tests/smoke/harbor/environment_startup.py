"""Opt-in concurrent startup check with frozen images; no agent or model calls."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths
    from src.execution.adapters.quantum_harbor.pinned_environment import PinnedDockerEnvironment
    from src.execution.host.container_runtime import PODMAN_SINGLE_UID, policy, compose_security

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quantum-harbor', type=Path, required=True)
    parser.add_argument('--lock', type=Path, required=True, help='One task image lock JSON')
    parser.add_argument('--task', default='time_budgeted_hamlearn_10q')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--concurrency', type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    assert policy() == PODMAN_SINGLE_UID, 'This check targets the single-UID Podman policy'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    task = args.quantum_harbor.resolve()/'harbor_tasks'/args.task
    config = TaskConfig.model_validate(tomllib.loads((task/'task.toml').read_text()))
    images = json.loads(args.lock.read_text())['images']

    async def run(index):
        paths = TrialPaths(output/str(index))
        paths.mkdir()
        env = PinnedDockerEnvironment(environment_dir=task/'environment',
            environment_name='phyexp-startup-check', session_id='phyexp-startup-'+uuid.uuid4().hex,
            trial_paths=paths, task_env_config=config.environment, pinned_images=images)
        resources = {}
        try:
            await env.start()
            resources = json.loads((paths.trial_dir/'phyexp/pinned-resources-agent.json').read_text())
            inspected = json.loads(subprocess.check_output(['docker', 'inspect', resources['qsim']['container']], text=True))[0]
            actual_env = dict(value.split('=', 1) for value in inspected['Config']['Env'])
            for key, value in compose_security('qsim')['environment'].items():
                assert actual_env[key] == value, (key, actual_env.get(key))
            assert inspected['State']['Health']['Status'] == 'healthy'
            receipt = json.loads((paths.trial_dir/'phyexp/environment-startup-agent.json').read_text())
            assert receipt['status'] == 'ready'
            assert receipt['elapsedSeconds'] < config.environment.build_timeout_sec
        finally:
            await env.stop()
        for resource in resources.values():
            assert subprocess.run(['docker', 'inspect', resource['container']], capture_output=True).returncode != 0
            for volume in resource['volumes']:
                assert subprocess.run(['docker', 'volume', 'inspect', volume], capture_output=True).returncode != 0
        return {'index': index, 'startup': receipt, 'resources': resources, 'cleanupVerified': True}

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda index: asyncio.run(run(index)), range(args.concurrency)))
    containers = [r['container'] for result in results for r in result['resources'].values()]
    volumes = [{v for r in result['resources'].values() for v in r['volumes']} for result in results]
    assert len(set(containers)) == len(containers)
    assert all(not a & b for i, a in enumerate(volumes) for b in volumes[i+1:])
    for role in ('main', 'qsim'):
        assert subprocess.check_output(['docker', 'image', 'inspect', images[role], '--format', '{{.Id}}'], text=True).strip() == images[role]
    summary = {'status': 'passed', 'modelCalls': 0, 'concurrency': args.concurrency, 'results': results}
    (output/'verification.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
