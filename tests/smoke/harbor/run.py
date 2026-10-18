#!/usr/bin/env python3
"""Run the official no-op installation check, with an explicit pass/fail result."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def collect(job_dir):
    job = json.loads((job_dir / 'result.json').read_text())
    stats = job['stats']
    if stats['n_completed_trials'] != 1 or stats['n_errored_trials'] != 0:
        raise ValueError('Expected one completed trial and zero infrastructure errors')
    trials = list(job_dir.glob('time_budgeted_hamlearn_10q__*/result.json'))
    if len(trials) != 1:
        raise ValueError('Expected exactly one trial result')
    trial = json.loads(trials[0].read_text())
    if trial.get('exception_info'):
        raise ValueError('Trial contains an exception')
    verifier = trials[0].parent / 'verifier'
    # A missing reward is an error, never a zero.
    reward = float((verifier / 'reward.txt').read_text().strip())
    score = json.loads((verifier / 'artifacts/score_report.json').read_text())
    if reward != 0 or score.get('reward_binary') != 0:
        raise ValueError('No-op agent should receive a real zero reward')
    if not any('missing final_answer.json' in p for p in score.get('penalties', [])):
        raise ValueError('Expected the no-submission diagnostic')
    return {'status': 'passed', 'task': 'time_budgeted_hamlearn_10q', 'agent': 'nop',
            'reward': reward, 'completedTrials': 1, 'errors': 0,
            'diagnostic': score['penalties'], 'jobDir': str(job_dir.resolve()),
            'rewardFile': str((verifier / 'reward.txt').resolve()),
            'scoreReport': str((verifier / 'artifacts/score_report.json').resolve())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quantum-harbor', type=Path, default=ROOT.parent / 'Quantum-Harbor')
    parser.add_argument('--collect', type=Path, help='Validate an existing job without rerunning')
    args = parser.parse_args()
    repo = args.quantum_harbor.resolve()
    if args.collect:
        job_dir = args.collect.resolve()
    else:
        run_id = 'phyexp-nop-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        jobs_dir = ROOT / 'runs/smoke'
        jobs_dir.mkdir(parents=True, exist_ok=True)
        job_dir = jobs_dir / run_id
        command = ['harbor', 'run', '-p', 'harbor_tasks/time_budgeted_hamlearn_10q',
                   '-a', 'nop', '-n', '1', '-k', '1', '-r', '0',
                   '--job-name', run_id, '-o', str(jobs_dir)]
        with (jobs_dir / f'{run_id}.console.log').open('w') as log:
            completed = subprocess.run(command, cwd=repo, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        if completed.returncode != 0:
            raise RuntimeError(f'Harbor exited with {completed.returncode}; see console log in {jobs_dir}')
    result = collect(job_dir)
    result['harborVersion'] = subprocess.check_output(['harbor', '--version'], text=True).strip()
    result['quantumHarborCommit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    result['quantumHarborDirty'] = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo, text=True).strip())
    task_config = repo / 'harbor_tasks/time_budgeted_hamlearn_10q/task.toml'
    result['taskConfigSha256'] = hashlib.sha256(task_config.read_bytes()).hexdigest()
    # Use the trial's frozen task identity. Tags inspected after cleanup are
    # neither guaranteed to exist nor evidence of which image the trial ran.
    lock = json.loads(next(job_dir.glob('time_budgeted_hamlearn_10q__*/lock.json')).read_text())
    result['taskDigest'] = lock['task']['digest']
    result['imageNote'] = 'Harbor default cleanup can remove the locally built qsim image; reruns rebuild it from the task compose definition.'
    output = job_dir / 'smoke-summary.json'
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
