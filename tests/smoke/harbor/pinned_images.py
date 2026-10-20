"""Opt-in Docker integration: run each public task twice with nop, never a model.

Checks immutable agent/qsim/verifier receipts, fresh containers and volumes,
cleanup, and cached preparations. No-submission outcomes come from the official
verifier; Shadow explicitly refuses a score when nop leaves an empty evidence log.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.control.store import PUBLIC_TASKS
from src.control.task_images import prepare_task_images, verify_locks
from src.execution.host.single_run import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quantum-harbor', type=Path, default=ROOT.parent/'Quantum-Harbor')
    parser.add_argument('--locks', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true', help='Collect finished jobs and run only missing tasks')
    args = parser.parse_args()
    root, output = args.quantum_harbor.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=args.resume)
    locks = {task:json.loads((args.locks/(task+'.json')).read_text()) for task in PUBLIC_TASKS}
    verify_locks(root, PUBLIC_TASKS, locks)
    preparation_log = output/('resume-reprepare.log' if args.resume else 'reprepare.log')
    prepared = prepare_task_images(root, PUBLIC_TASKS, args.cache, preparation_log)
    if prepared != locks: raise AssertionError('Repeated preparation changed image identities')
    if '"build"' in preparation_log.read_text(): raise AssertionError('Warm cache unexpectedly rebuilt images')
    results = []
    for task in PUBLIC_TASKS:
        config = {'job_name':task, 'jobs_dir':str(output), 'n_attempts':2, 'n_concurrent_trials':2,
                  'retry':{'max_retries':0}, 'environment':{'type':None,
                  'import_path':'src.execution.adapters.quantum_harbor.pinned_environment:PinnedDockerEnvironment',
                  'delete':True, 'force_build':False, 'kwargs':{'pinned_images':locks[task]['images']}},
                  'agents':[{'name':'nop'}], 'tasks':[{'path':str(root/'harbor_tasks'/task)}],
                  'verifier':{'disable':False}}
        job = output/task
        if not (args.resume and (job/'result.json').is_file()):
            config_path = output/(task+'.json'); write_json(config_path, config)
            with (output/(task+'.console.log')).open('w') as log:
                subprocess.run(['harbor','run','-c',str(config_path)], cwd=root,
                               env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONNOUSERSITE='1'),
                               stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
        summary = json.loads((job/'result.json').read_text())
        if summary['stats']['n_completed_trials']!=2:
            raise AssertionError('Expected two ended trials: '+task)
        trials = sorted(job.glob('*/result.json'))
        if len(trials)!=2: raise AssertionError('Missing trial results: '+task)
        resources, rewards, dispositions = [], [], []
        for file in trials:
            trial = json.loads(file.read_text())
            error = trial.get('exception_info')
            reward_file = file.parent/'verifier/reward.txt'
            if task=='time_budgeted_shadow_surrogate_60q' and error:
                diagnostic = (file.parent/'verifier/test-stdout.txt').read_text()
                if error['exception_type']!='RewardFileNotFoundError' or 'no submission AND empty evidence log: bootstrap suspect' not in diagnostic or reward_file.exists():
                    raise AssertionError(error)
                reward = None
                dispositions.append('official verifier refuses empty nop evidence; unscored')
            else:
                if error: raise AssertionError(error)
                reward = float(reward_file.read_text())
                if reward!=0: raise AssertionError('Nop must receive an official zero, not a fabricated success')
                dispositions.append('official no-submission zero')
            rewards.append(reward)
            used = {}
            for role in ('agent','verifier'):
                actual = json.loads((file.parent/'phyexp'/('pinned-images-'+role+'.json')).read_text())
                expected = {'main':locks[task]['images']['verifier']} if role=='verifier' else {
                    key:locks[task]['images'][key] for key in ('main','qsim')}
                if actual!=expected: raise AssertionError('Actual container image differs from frozen lock')
                receipt = json.loads((file.parent/'phyexp'/('pinned-resources-'+role+'.json')).read_text())
                used.update({role+'/'+key:value for key,value in receipt.items()})
            resources.append(used)
        old, new = resources
        if {v['container'] for v in old.values()} & {v['container'] for v in new.values()}:
            raise AssertionError('Trials reused a container')
        old_volumes = {v for r in old.values() for v in r['volumes']}
        new_volumes = {v for r in new.values() for v in r['volumes']}
        if not old_volumes or not new_volumes or old_volumes & new_volumes:
            raise AssertionError('Trials reused volumes or volume evidence is missing')
        for resource in list(old.values())+list(new.values()):
            if subprocess.run(['docker','inspect',resource['container']],capture_output=True).returncode==0:
                raise AssertionError('Trial container survived cleanup')
        for volume in old_volumes | new_volumes:
            if subprocess.run(['docker','volume','inspect',volume],capture_output=True).returncode==0:
                raise AssertionError('Trial volume survived cleanup')
        verify_locks(root, [task], locks)
        results.append({'task':task,'trials':2,'identicalImages':True,'freshContainersAndVolumes':True,
                        'cleanupPreservedImages':True,'officialRewards':rewards,'verifierOutcomes':dispositions})
        write_json(output/'verification.json', {'status':'in_progress','results':results,'modelCalls':0})
        print('PASS '+task, flush=True)
    write_json(output/'verification.json', {'status':'passed','results':results,'modelCalls':0})


if __name__ == '__main__':
    main()
