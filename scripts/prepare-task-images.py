"""Prepare immutable official task images without running Solver or changing task files."""
import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.execution.host.single_run import source_hashes, validate_task_image_lock

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--quantum-harbor', type=Path, required=True)
parser.add_argument('--task', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = args.quantum_harbor.resolve()
task = root / 'harbor_tasks' / args.task
if '/' in args.task or not (task / 'task.toml').is_file():
    raise SystemExit('Task unavailable')
sources = source_hashes(root, ['src', 'configs', 'docker', 'harbor_tasks'])
digest = hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
base = subprocess.check_output(['docker', 'image', 'inspect', 'qiqcbench-agent:latest', '--format', '{{.Id}}'], text=True).strip()
tag = 'phyexp-task:' + hashlib.sha256((digest+base).encode()).hexdigest()[:20]
subprocess.run(['docker', 'tag', base, tag+'-base'], check=True)
subprocess.run(['docker', 'build', '--build-arg', 'AGENT_IMAGE='+tag+'-base', '-t', tag+'-main', str(task/'environment')], check=True, timeout=600)
subprocess.run(['docker', 'build', '-t', tag+'-qsim', '-f', str(root/'docker/qsim/Dockerfile'), str(root)], check=True, timeout=600)
config = tomllib.loads((task/'task.toml').read_text())
verifier_source = config['verifier']['environment']['docker_image']
images = {role: subprocess.check_output(['docker', 'image', 'inspect', name, '--format', '{{.Id}}'], text=True).strip()
          for role, name in {'main': tag+'-main', 'qsim': tag+'-qsim', 'verifier': verifier_source}.items()}
images['verifierSource'] = verifier_source
lock = {'schemaVersion': 1, 'task': args.task, 'taskSourcesDigest': digest, 'images': images,
        'source': 'Official Dockerfiles and existing official verifier image; only image provisioning is frozen.'}
validate_task_image_lock(lock, args.task, source_hashes(root, ['src', 'configs', 'docker', 'harbor_tasks']))
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(lock, indent=2)+'\n')
print(json.dumps(lock, indent=2))
