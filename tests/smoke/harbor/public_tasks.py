"""Opt-in single-UID Podman acceptance using deterministic probes, no models.

Provision official base/verifier images first. This test uses the production
image locks, container adapter, network restriction, MCP and official verifier.
It does not claim scientific success or model performance.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.control.store import PUBLIC_TASKS
from src.control.task_images import prepare_task_images, verify_locks
from src.execution.adapters.quantum_harbor.results import official_assessment
from src.execution.host.single_run import write_json
from src.execution.host.container_runtime import PODMAN_SINGLE_UID, policy, preflight


def collect(output, task, lock):
    job = output/task
    summary = json.loads((job/'result.json').read_text())
    assert summary['stats']['n_completed_trials'] == 1, summary['stats']
    assert summary['stats']['n_errored_trials'] == 0, summary['stats']
    files = list(job.glob('*/result.json'))
    assert len(files) == 1, files
    trial_dir = files[0].parent
    trial = json.loads(files[0].read_text())
    assert not trial.get('exception_info'), trial.get('exception_info')
    reward = float((trial_dir/'verifier/reward.txt').read_text())
    score = json.loads((trial_dir/'verifier/artifacts/score_report.json').read_text())
    assert official_assessment(score, reward), score
    assert score['task_id'] == task, score
    assert (trial_dir/'verifier/artifacts/final_answer.json').is_file()
    assert (trial_dir/'verifier/artifacts/experiment_log.jsonl').stat().st_size > 0
    probe = json.loads((trial_dir/'phyexp/probe-result.json').read_text())
    assert probe['completedJobs'] and probe['modelCalls'] == 0, probe
    isolation = probe['isolation']
    cpu = 4 if task == 'time_budgeted_shadow_surrogate_60q' else 2
    memory = 6 if task == 'logical_cnot_decoder_calibration' else 4
    quota, period = map(int, isolation['cpuMax'].split())
    assert quota/period == cpu and int(isolation['memoryMax']) == memory*1024**3, isolation
    assert int(isolation['pidsMax']) == 256, isolation
    assert probe['submission'].get('accepted') is True, probe['submission']
    inspected = json.loads((trial_dir/'phyexp/probe-containers.json').read_text())
    default_caps = {'AUDIT_WRITE','CHOWN','DAC_OVERRIDE','FOWNER','FSETID','KILL','MKNOD',
                    'NET_BIND_SERVICE','NET_RAW','SETFCAP','SETGID','SETPCAP','SETUID','SYS_CHROOT'}
    for item in inspected:
        host = item['hostConfig']
        # Podman's Docker-compatible inspect expands ALL into capability names.
        dropped = set(host['CapDrop'] or [])
        assert not host['Privileged'] and ('ALL' in dropped or default_caps <= dropped), host
        assert any(option.startswith('no-new-privileges') for option in host['SecurityOpt']), host
    resources = {}
    for role in ('agent','verifier'):
        images = json.loads((trial_dir/'phyexp'/('pinned-images-'+role+'.json')).read_text())
        expected = {'main':lock['images']['verifier']} if role == 'verifier' else {
            key:lock['images'][key] for key in ('main','qsim')}
        assert images == expected, (images, expected)
        receipt = json.loads((trial_dir/'phyexp'/('pinned-resources-'+role+'.json')).read_text())
        resources.update({role+'/'+key:value for key,value in receipt.items()})
    for resource in resources.values():
        assert subprocess.run(['docker','inspect',resource['container']], capture_output=True).returncode != 0
        for volume in resource['volumes']:
            assert subprocess.run(['docker','volume','inspect',volume], capture_output=True).returncode != 0
    return {'task':task,'status':'passed','kind':'deployment_fixture','modelCalls':0,
            'officialReward':reward,'scientificAssessmentPresent':True,
            'completedProbeJobs':len(probe['completedJobs']),'resources':resources,
            'isolation':probe['isolation'],'trialDir':str(trial_dir)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quantum-harbor', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tasks', nargs='+', choices=PUBLIC_TASKS, default=list(PUBLIC_TASKS))
    parser.add_argument('--concurrency', type=int, choices=(1,2), default=2)
    args = parser.parse_args()
    if policy() != PODMAN_SINGLE_UID:
        parser.error('This acceptance check requires PHYEXP_CONTAINER_RUNTIME='+PODMAN_SINGLE_UID)
    preflight(args.tasks)
    root, output = args.quantum_harbor.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.time()
    locks = prepare_task_images(root, args.tasks, args.cache, output/'prepare.log')
    write_json(output/'locks.json', locks)
    prepared = prepare_task_images(root, args.tasks, args.cache, output/'cached-prepare.log')
    assert prepared == locks, 'Warm preparation changed frozen image identities'
    assert '"build"' not in (output/'cached-prepare.log').read_text(), 'Warm cache rebuilt images'

    def run(task):
        config = {'job_name':task,'jobs_dir':str(output),'n_attempts':1,'n_concurrent_trials':1,
            'retry':{'max_retries':0},'environment':{'type':None,'delete':True,'force_build':False,
            'import_path':'src.execution.adapters.quantum_harbor.pinned_environment:PinnedDockerEnvironment',
            'kwargs':{'pinned_images':locks[task]['images']}},
            'agents':[{'import_path':'tests.fixtures.public_task_probe_agent:PublicTaskProbeAgent',
                       'override_timeout_sec':600,'kwargs':{'task':task}}],
            'tasks':[{'path':str(root/'harbor_tasks'/task)}],'verifier':{'disable':False}}
        file = output/(task+'.json'); write_json(file, config)
        with (output/(task+'.console.log')).open('w') as log:
            subprocess.run(['harbor','run','-c',str(file)],cwd=root,
                env=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONNOUSERSITE='1'),
                stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1800)
        return collect(output, task, locks[task])

    results, failures = [], []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run, task):task for task in args.tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                results.append(future.result())
                print('PASS '+task, flush=True)
            except Exception as error:
                failures.append({'task':task,'error':str(error)})
                print('FAIL '+task+': '+str(error), flush=True)
            write_json(output/'verification.json',{'status':'in_progress','results':results,'failures':failures,'modelCalls':0})
    containers, volumes = set(), set()
    for result in results:
        used = result['resources'].values()
        task_containers = {item['container'] for item in used}
        task_volumes = {name for item in used for name in item['volumes']}
        assert task_volumes and not task_containers & containers and not task_volumes & volumes
        containers.update(task_containers); volumes.update(task_volumes)
    verify_locks(root, args.tasks, locks)
    write_json(output/'verification.json',{'status':'failed' if failures else 'passed',
        'results':results,'failures':failures,'modelCalls':0,'concurrency':args.concurrency,
        'elapsedSeconds':time.time()-started,'freshContainersAndVolumes':True})
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
