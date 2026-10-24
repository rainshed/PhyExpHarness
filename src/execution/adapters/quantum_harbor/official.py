"""Versioned official-result projection, independent of candidate diagnostics.

Only the trusted adapter/Harbor output directory is an input. Candidate stdout
or its own reported score is never an authority. Legacy collectors stay frozen.
"""
import hashlib
import json
from pathlib import Path

VERSION = 'official-result-v3'


def collect(root, *, bundle_id=None, task=None, archived=False):
    from .results import official_assessment
    root = Path(root).resolve()
    sources, gaps = {}, []
    manifest = json.loads((root / 'archive-manifest.json').read_text())['files'] if archived else None

    def read(relative, *, text=False):
        path = root / relative
        if (not path.resolve().is_relative_to(root) or
                any(p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents)):
            raise ValueError('Escaping official evidence: ' + relative)
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if manifest is not None and manifest.get(relative) != {'bytes': len(data), 'sha256': sha}:
            raise ValueError('Official evidence changed or is not archived: ' + relative)
        sources[relative] = sha
        return data.decode() if text else json.loads(data)

    provenance = read('provenance.json')
    if bundle_id is not None and provenance['bundleId'] != bundle_id:
        raise ValueError('Official archive belongs to another candidate')
    if task is not None and provenance['task'] != task:
        raise ValueError('Official archive belongs to another task')
    paths = list((root / 'harbor').glob('*/result.json'))
    if len(paths) != 1:
        raise ValueError('Expected exactly one Harbor Trial')
    relative = paths[0].relative_to(root).as_posix()
    base = paths[0].parent.relative_to(root).as_posix()
    trial = read(relative)
    if trial['task_name'] != provenance['task']:
        raise ValueError('Harbor Trial belongs to another task')
    lock = read(base + '/lock.json')
    reward_path, score_path = base + '/verifier/reward.txt', base + '/verifier/artifacts/score_report.json'
    reward = float(read(reward_path, text=True).strip())
    score = read(score_path)
    assessed = official_assessment(score, reward)
    if (trial.get('verifier_result') or {}).get('rewards', {}).get('reward') != reward:
        raise ValueError('Harbor and official reward disagree')
    if score.get('task_id') != trial['task_name']:
        raise ValueError('Official score belongs to another task')
    answer_path = base + '/verifier/artifacts/final_answer.json'
    submitted = (root / answer_path).is_file()
    if submitted:
        # An invalid scientific submission is still an official outcome. Its
        # exact bytes are evidence, not a reason to erase the verifier result.
        read(answer_path, text=True)
    if reward == 1 and (not submitted or not assessed):
        raise ValueError('Passing reward requires submission and assessment')

    runtime = {}
    runtime_path = base + '/phyexp/runtime-summary.json'
    for name in (runtime_path, base + '/phyexp/events.json', base + '/verifier/artifacts/experiment_log.jsonl'):
        try:
            value = read(name, text=True)
            if name == runtime_path:
                runtime = json.loads(value)
                if runtime.get('bundleId') != provenance['bundleId']:
                    gaps.append({'path': name, 'reason': 'candidate_identity_mismatch'})
            elif name.endswith('events.json'):
                json.loads(value)
            else:
                for line in value.splitlines():
                    if line.strip(): json.loads(line)
        except (OSError, ValueError) as error:
            gaps.append({'path': name, 'reason': str(error)})
    exception = trial.get('exception_info')
    execution = runtime.get('status') or ('error' if exception else 'completed')
    recipe = provenance.get('recipe', {})
    return {
        'resultContract': VERSION, 'pipelineStatus': 'completed',
        'status': 'completed' if submitted and assessed else 'incomplete',
        'task': trial['task_name'], 'trial': trial['trial_name'],
        'bundleId': provenance['bundleId'], 'taskDigest': lock['task']['digest'],
        'model': recipe.get('model'), 'provider': recipe.get('provider'),
        'officialReward': reward, 'sciencePassed': reward == 1, 'score': score,
        'scoringStatus': 'completed', 'submissionPresent': submitted,
        'scientificAssessmentPresent': assessed,
        'taskOutcome': ('no_submission' if not submitted else 'invalid_submission' if not assessed
                        else 'passed' if reward else 'failed_science'),
        'execution': {'status': execution, 'exception': exception, 'exitCode': runtime.get('exitCode')},
        'officialResult': {'status': 'available', 'sources': {k: sources[k] for k in
            ('provenance.json', relative, base + '/lock.json', reward_path, score_path)}},
        'evidenceStatus': {'status': 'partial' if gaps else 'complete', 'gaps': gaps},
        'comparison': {'status': 'identity_verified', 'bundleId': provenance['bundleId']},
        'runtime': runtime,
        'evidence': {'harborResult': relative, 'officialReward': reward_path, 'officialScore': score_path,
                     **({'submission': answer_path} if submitted else {})},
        'resultCollection': {'version': VERSION, 'sourceDigests': sources},
    }


def unavailable(root, error, *, bundle_id=None, task=None, stopped=None):
    """Preserve independent execution diagnostics when official output is absent.

    Diagnostics are explicitly not score authority. A damaged diagnostic cannot
    replace the original collection error or manufacture a verifier result.
    """
    root = Path(root); runtime = {}; exception = None; gaps = []
    for pattern, kind in [('harbor/*/phyexp/runtime-summary.json','runtime'), ('harbor/*/result.json','harbor')]:
        paths = list(root.glob(pattern))
        if len(paths) != 1: continue
        try:
            path=paths[0]
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()): raise ValueError('Unsafe diagnostic path')
            value=json.loads(path.read_text())
            if kind == 'runtime': runtime=value
            else: exception=value.get('exception_info')
        except (OSError,ValueError) as failure: gaps.append({'path':pattern,'reason':str(failure)})
    return {'resultContract':VERSION,'pipelineStatus':'failed','status':'infrastructure_error',
        'task':task,'bundleId':bundle_id,'officialReward':None,'scoringStatus':'unavailable',
        'execution':{'status':stopped or runtime.get('status') or ('error' if exception else 'unknown'),
                     'exitCode':runtime.get('exitCode'),'exception':exception or runtime.get('exception')},
        'officialResult':{'status':'unavailable' if isinstance(error,OSError) else 'invalid_source',
                          'errorType':type(error).__name__,'message':str(error)},
        'evidenceStatus':{'status':'partial','gaps':gaps},'comparison':{'status':'identity_unverified'},
        'runtime':runtime,'failure':{'code':'official_result_unavailable','stage':'collection','message':str(error)},
        'stopReason':stopped,'resultCollection':{'version':VERSION}}
