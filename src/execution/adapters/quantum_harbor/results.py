"""Read authoritative Harbor results; missing/corrupt evidence never means zero."""
import hashlib
import json
import subprocess
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text())


def official_assessment(score, reward):
    """Validate released report envelopes; never recalculate scientific grades."""
    if reward not in (0, 1):
        raise ValueError('Official reward must be binary')
    indicators = []
    for key in ('reward_binary', 'reward'):
        if key in score:
            if type(score[key]) is not int or score[key] != reward:
                raise ValueError('Official reward and score report disagree')
            indicators.append(key)
    if 'passed' in score:
        if type(score['passed']) is not bool or score['passed'] is not bool(reward):
            raise ValueError('Official reward and score report disagree')
        indicators.append('passed')
    if not indicators:
        raise ValueError('Official report has no recognized verdict')
    if 'result' in score:  # Hamiltonian learning
        assessed = isinstance(score['result'], dict)
        if assessed and score['result'].get('binary_pass') is not bool(reward):
            raise ValueError('Scientific result and reward disagree')
        return assessed
    if 'disposition' in score:  # Shadow surrogate and logical CNOT
        if score['disposition'] not in ('scored', 'model_failure'):
            raise ValueError('Unexpected official report disposition')
        return score['disposition'] == 'scored'
    # CZ and H2O put scientific checks directly in the report. Rejections
    # before scientific replay have a verdict but no checks.
    return isinstance(score.get('checks'), dict) or isinstance(score.get('admission_checks'), dict)


def collect(run_dir):
    run_dir = Path(run_dir)
    job = read_json(run_dir / 'harbor/result.json')
    stats = job['stats']
    trials = list((run_dir / 'harbor').glob('*/result.json'))
    if stats['n_completed_trials'] != 1 or stats['n_errored_trials'] != 0 or len(trials) != 1:
        raise ValueError('Expected exactly one completed trial and no infrastructure errors')
    trial = read_json(trials[0])
    if trial.get('exception_info'):
        raise ValueError('Harbor trial contains an exception')
    base = trials[0].parent
    runtime = read_json(base / 'phyexp/runtime-summary.json')
    if runtime['status'] != 'completed' or runtime['toolCalls'] < 1:
        raise ValueError('No completed Solver/tool execution')
    reward_path = base / 'verifier/reward.txt'
    score_path = base / 'verifier/artifacts/score_report.json'
    reward = float(reward_path.read_text().strip())
    score = read_json(score_path)
    assessed = official_assessment(score, reward)
    if trial['verifier_result']['rewards']['reward'] != reward:
        raise ValueError('Harbor result and official reward file disagree')
    if score['task_id'] != trial['task_name']:
        raise ValueError('Official report belongs to another task')
    answer = base / 'verifier/artifacts/final_answer.json'
    experiments = base / 'verifier/artifacts/experiment_log.jsonl'
    if not experiments.is_file() or not experiments.stat().st_size:
        raise ValueError('Missing qsim experiment evidence')
    experiment_events = [json.loads(line) for line in experiments.read_text().splitlines() if line.strip()]
    submitted = answer.is_file()
    if submitted:
        read_json(answer)
    if reward == 1 and (not submitted or not assessed):
        raise ValueError('Passing reward requires a submission and scientific assessment')
    def rel(p):
        return str(p.relative_to(run_dir))
    result = {
        'status': 'completed' if submitted and assessed else 'incomplete',
        'pipelineStatus': 'completed',
        'taskOutcome': ('no_submission' if not submitted else 'invalid_submission' if not assessed
                        else 'passed' if reward else 'failed_science'),
        'task': trial['task_name'], 'trial': trial['trial_name'],
        # Recipe labels are optional in v2; the frozen bundle owns execution identity.
        'recipeId': runtime['recipe'].get('id'), 'bundleId': runtime.get('bundleId'),
        'model': runtime['model'], 'provider': runtime['provider'],
        'scoringStatus': 'completed',
        'officialReward': reward, 'sciencePassed': reward == 1,
        'submissionPresent': submitted, 'scientificAssessmentPresent': assessed,
        'qsimActions': sorted({e['action'] for e in experiment_events if 'action' in e}),
        'completedProbeBatches': sum(e.get('action') == 'probe_batch_result' for e in experiment_events),
        'score': score, 'runtime': runtime,
        **({k:runtime.get(k) for k in ['failureContract','requestRecovery']} if runtime.get('failureContract') else {}),
        'taskDigest': read_json(base / 'lock.json')['task']['digest'],
        'evidence': {'harborResult': rel(trials[0]), 'officialReward': rel(reward_path),
                     'officialScore': rel(score_path), 'qsimExperiments': rel(experiments),
                     'runtime': rel(base / 'phyexp/runtime-summary.json'),
                     'trace': rel(base / 'phyexp/events.json'), 'workspace': rel(base / 'phyexp/workspace')},
    }
    if submitted:
        result['evidence']['submission'] = rel(answer)
    # Recalculate presentation metrics from the immutable trajectory; never rewrite raw runtime/Harbor results.
    module = Path(__file__).resolve().parents[2] / 'host/usage.mjs'
    script = "import fs from 'node:fs'; const {summarizeUsage}=await import(process.argv[1]); console.log(JSON.stringify(summarizeUsage(JSON.parse(fs.readFileSync(process.argv[2])))));"
    events = base / 'phyexp/events.json'
    if events.is_file():
        result['usage'] = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', script,
            module.as_uri(), str(events)], text=True))
    else:
        raise ValueError('Missing durable Solver trajectory')
    return result


def archive_manifest(run_dir):
    run_dir = Path(run_dir)
    files = {}
    for path in sorted(run_dir.rglob('*')):
        if path.is_file() and path.name != 'archive-manifest.json' and not path.is_symlink():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            files[str(path.relative_to(run_dir))] = {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}
    (run_dir / 'archive-manifest.json').write_text(json.dumps({'algorithm': 'sha256', 'files': files}, indent=2) + '\n')
    return len(files)


def verify_manifest(run_dir):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / 'archive-manifest.json')
    for relative, expected in manifest['files'].items():
        path = run_dir / relative
        if not path.resolve().is_relative_to(run_dir.resolve()):
            raise ValueError(f'Archive path escapes run directory: {relative}')
        if not path.is_file() or path.is_symlink() or path.stat().st_size != expected['bytes']:
            raise ValueError(f'Archive file missing or changed: {relative}')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected['sha256']:
            raise ValueError(f'Archive digest mismatch: {relative}')
    return len(manifest['files'])
