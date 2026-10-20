"""Independent one-Trial supervisor. All execution imports are rooted in a verified Bundle."""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from ..bundle.freeze import verify
from .network import provider_environment
from ..adapters.quantum_harbor.results import collect, archive_manifest, verify_manifest

TRIAL_CLOSEOUT_RESERVE_SECONDS = 330


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def source_hashes(root, paths):
    result = {}
    for relative in paths:
        source = Path(root) / relative
        for p in sorted(source.rglob('*') if source.is_dir() else [source]):
            if p.is_file() and '__pycache__' not in p.parts and p.name != '.DS_Store':
                result[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


def task_image_sources(root, version=2):
    if version not in (1, 2):
        raise ValueError('Unsupported task image lock version')
    paths = ['src', 'configs', 'docker', 'harbor_tasks']
    if version == 2:
        paths += ['pyproject.toml', 'README.md', '.dockerignore', 'uv.lock']
    return source_hashes(root, paths)


def validate_task_image_lock(lock, task, sources):
    digest = hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    if lock.get('task') != task or lock.get('taskSourcesDigest') != digest:
        raise ValueError('Task image lock does not match current task sources; prepare a new environment')
    images = lock.get('images', {})
    if any(not re.fullmatch(r'sha256:[0-9a-f]{64}', images.get(role, '')) for role in ['main', 'qsim', 'verifier']):
        raise ValueError('Task image lock must contain immutable image identities')
    return images


def cleanup(output):
    actions = []
    if not Path(output).exists():return actions
    for file in Path(output).glob('harbor/*/phyexp/runner-identity.json'):
        identity = json.loads(file.read_text())
        name = identity['container']
        if name.startswith('phyexp-runner-'):
            result = subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
            actions.append({'container': name, 'returnCode': result.returncode})
    for file in Path(output).glob('harbor/*/phyexp/isolation.json'):
        identity = json.loads(file.read_text())
        for name in ['main', 'qsim']:
            subprocess.run(['docker', 'rm', '-f', identity[name]], capture_output=True)
        subprocess.run(['docker', 'network', 'rm', identity['network']], capture_output=True)
    # Recover the small crash window between internal-network creation and identity-file persistence.
    owned=subprocess.run(['docker','network','ls','-q','--filter','label=phyexp.launch='+Path(output).name],capture_output=True,text=True)
    for network in owned.stdout.split():
        details=subprocess.run(['docker','network','inspect',network],capture_output=True,text=True)
        if details.returncode==0:
            for container in json.loads(details.stdout)[0].get('Containers',{}):
                subprocess.run(['docker','rm','-f',container],capture_output=True)
        subprocess.run(['docker','network','rm',network],capture_output=True)
    return actions


def run(bundle_root, quantum_harbor, task_name, output, deadline, soft_token_limit=3_000_000, task_image_lock=None):
    bundle_root, quantum_harbor, output = map(lambda p: Path(p).resolve(), [bundle_root, quantum_harbor, output])
    bundle = verify(bundle_root)
    recipe = json.loads((bundle_root / 'recipe.json').read_text())
    task = quantum_harbor / 'harbor_tasks' / task_name
    if '/' in task_name or not (task / 'task.toml').is_file():
        raise ValueError('Task unavailable')
    output.mkdir(parents=True, exist_ok=False)
    started = time.time()
    process = None
    stopped = {'reason': None}
    def stop(_sig, _frame):
        stopped['reason'] = 'user_stop'
    previous = signal.signal(signal.SIGTERM, stop)
    provenance = {'schemaVersion':1, 'startedAt':now(), 'bundleId':bundle['id'], 'bundleRoot':str(bundle_root),
        'recipe':recipe, 'deadline':deadline, 'task':task_name, 'softTokenLimit':soft_token_limit,
        'trialCloseoutReserveSeconds':TRIAL_CLOSEOUT_RESERVE_SECONDS,
        'quantumHarbor':{'path':str(quantum_harbor), 'sourceHashes':source_hashes(quantum_harbor,['src','configs','docker','harbor_tasks'])}}
    write_json(output / 'provenance.json', provenance)
    write_json(output / 'supervisor.json', {'pid':os.getpid(), 'startedAt':now(), 'deadline':deadline, 'state':'starting'})
    try:
        remaining = deadline - time.time()
        if remaining <= TRIAL_CLOSEOUT_RESERVE_SECONDS:
            raise TimeoutError('Insufficient time for startup and official verification')
        # No generated plugin is loaded during this host preflight.
        auth = "import fs from 'node:fs';import {createProviderCredentials} from './src/execution/host/provider_auth.mjs';const c=createProviderCredentials(JSON.parse(fs.readFileSync('recipe.json')),{minimumValidityMs:Number(process.argv[1])});c.dispose();"
        subprocess.run(['node', '--input-type=module', '-e', auth, str(int((remaining+120)*1000))], cwd=bundle_root, check=True)
        image = subprocess.run(['docker', 'image', 'inspect', bundle['runnerImage'], '--format', '{{.Id}}'], text=True, capture_output=True, check=True).stdout.strip()
        provenance['runnerImageId'] = image
        solver_deadline = min(deadline - TRIAL_CLOSEOUT_RESERVE_SECONDS, time.time() + recipe['agentTimeoutSec'])
        provenance['solverDeadline']=solver_deadline
        config = {'job_name':'harbor', 'jobs_dir':str(output), 'n_attempts':1, 'n_concurrent_trials':1,
            'retry':{'max_retries':0}, 'environment':{'type':'docker','delete':True,'force_build':False},
            'agents':[{'import_path':bundle['agentEntry'], 'model_name':f'{recipe["provider"]}/{recipe["model"]}',
                'override_timeout_sec':max(1,solver_deadline-time.time()),
                'kwargs':{'bundle_root':str(bundle_root),'deadline':solver_deadline}}],
            'tasks':[{'path':str(task)}], 'verifier':{'disable':False}}
        if task_image_lock:
            lock = json.loads(Path(task_image_lock).read_text())
            images = validate_task_image_lock(lock, task_name, task_image_sources(quantum_harbor, lock.get('schemaVersion', 1)))
            for role in ['main', 'qsim', 'verifier']:
                actual = subprocess.check_output(['docker', 'image', 'inspect', images[role], '--format', '{{.Id}}'], text=True).strip()
                if actual != images[role]: raise ValueError('Frozen task image is unavailable: '+role)
            provenance['taskImageLock'] = lock
            config['environment'].update(type=None, import_path='src.execution.adapters.quantum_harbor.pinned_environment:PinnedDockerEnvironment', kwargs={'pinned_images':images})
        write_json(output / 'harbor-config.json', config)
        env = dict(provider_environment(), PYTHONPATH=str(bundle_root), PHYEXP_RUN_TOKEN_LIMIT=str(soft_token_limit or ''))
        # Disallow a parent checkout from winning module resolution.
        env['PYTHONNOUSERSITE'] = '1'
        env['PHYEXP_RUNNER_IMAGE_ID'] = image
        harbor = shutil.which('harbor')
        if not harbor:
            raise RuntimeError('Install the declared Harbor Python dependency first')
        with (output / 'console.log').open('w') as log:
            process = subprocess.Popen([harbor,'run','-c',str(output/'harbor-config.json')], cwd=quantum_harbor,
                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            while process.poll() is None:
                if time.time() >= deadline:
                    stopped['reason'] = 'trial_deadline'
                if stopped['reason']:
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    break
                write_json(output/'supervisor.json', {'pid':os.getpid(), 'childPid':process.pid, 'state':'running', 'deadline':deadline,'heartbeat':time.time()})
                time.sleep(.5)
        write_json(output/'process.json', {'harborExitCode':process.returncode,'stopReason':stopped['reason']})
        result = collect(output)
    except Exception as error:
        from .failure import failed_result
        result = failed_result(output, error, stopped['reason'])
    finally:
        signal.signal(signal.SIGTERM, previous)
        if process and process.poll() is None:
            os.killpg(process.pid,signal.SIGKILL);process.wait()
        actions = cleanup(output)
        provenance.update(finishedAt=now(), wallTimeSeconds=time.time()-started)
        write_json(output/'provenance.json', provenance)
    result.update(runId=output.name,runDir=str(output),bundleId=bundle['id'],wallTimeSeconds=time.time()-started,cleanup=actions)
    write_json(output/'summary.json', result)
    write_json(output/'supervisor.json', {'pid':os.getpid(),'state':'finished','deadline':deadline,'finishedAt':now()})
    archive_manifest(output)
    return result


def main(bundle_root=None, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    if bundle_root is None: parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--quantum-harbor',type=Path)
    parser.add_argument('--task')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--timeout',type=float,default=3600)
    parser.add_argument('--deadline',type=float)
    parser.add_argument('--soft-token-limit',type=lambda x:None if x=='none' else int(x),default=3_000_000,help='Positive soft threshold, or none for no token cap')
    parser.add_argument('--task-image-lock',type=Path,help='Operator-prepared immutable task image identities')
    parser.add_argument('--verify',action='store_true')
    parser.add_argument('--collect',type=Path)
    args = parser.parse_args(argv)
    bundle_root = bundle_root or args.bundle
    if args.verify:
        print(json.dumps({'bundleId':verify(bundle_root)['id'],'status':'verified'}));return 0
    if args.collect:
        verify_manifest(args.collect);print(json.dumps(collect(args.collect)));return 0
    if not all([args.quantum_harbor,args.task,args.output]) or args.timeout<=0 or (args.soft_token_limit is not None and args.soft_token_limit<=0):
        parser.error('Explicit task, environment and output; positive time/token limits are required')
    deadline = min(args.deadline or float('inf'),time.time()+args.timeout)
    result = run(bundle_root,args.quantum_harbor,args.task,args.output,deadline,args.soft_token_limit,args.task_image_lock)
    print(json.dumps({k:result.get(k) for k in ['runId','status','officialReward','stopReason']},ensure_ascii=False))
    return 0 if result['status']=='completed' else 1
