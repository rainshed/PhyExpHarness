"""Re-read known collector defects without changing frozen execution or raw archives."""
import hashlib
import json
from pathlib import Path

from src.execution.adapters.quantum_harbor import results
from src.execution.bundle.manifest import verify
from src.execution.host import failure

VERSION = 'result-collection-v2'


def read_summary(trial, candidate):
    root = Path(trial['output'])
    bundle = verify(candidate['bundlePath'])
    if bundle.get('schemaVersion') == 3:
        from src.execution.adapters.quantum_harbor.official import collect
        if bundle['id'] != candidate['bundleId']:
            raise ValueError('Candidate identity mismatch')
        try:
            summary = collect(root, bundle_id=bundle['id'], task=trial['task'], archived=True)
        except (OSError, ValueError, KeyError) as error:
            # Failed or damaged official output remains a visible unscored
            # attempt. No frozen diagnostic value can manufacture a score.
            summary = {'resultContract':'official-result-v3','pipelineStatus':'failed',
                'status':'infrastructure_error','officialReward':None,'scoringStatus':'unavailable',
                'task':trial['task'],'bundleId':bundle['id'],
                'officialResult':{'status':'not_run' if isinstance(error,FileNotFoundError) else 'invalid_source'},
                'execution':{'status':'unknown'},'evidenceStatus':{'status':'partial','error':str(error)},
                'comparison':{'status':'identity_unverified'},
                'failure':{'code':'official_result_unavailable','stage':'collection','message':str(error)},
                'resultCollection':{'version':'official-result-v3'}}
        summary.update(runId=root.name, runDir=str(root))
        return summary
    results.verify_manifest(root)
    original = results.read_json(root / 'summary.json')
    if original.get('pipelineStatus') != 'failed' or original.get('officialReward') is not None:
        return original
    recipe_error = original.get('error') == "'id'"
    bridge_error = (original.get('failure') or {}).get('code') in {'runtime_failed', 'container_transport_error'}
    if not recipe_error and not bridge_error:
        return original
    runtimes = list(root.glob('harbor/*/phyexp/runtime-summary.json'))
    if len(runtimes) != 1:
        return original
    runtime = results.read_json(runtimes[0])
    diagnosed = failure.diagnose(root)
    if not recipe_error and diagnosed['code'] != 'container_transport_error':
        return original
    bundle = verify(candidate['bundlePath'])
    provenance = results.read_json(root / 'provenance.json')
    if (bundle['id'] != candidate['bundleId'] or runtime.get('bundleId') != bundle['id']
            or provenance.get('bundleId') != bundle['id'] or provenance.get('task') != trial['task']):
        raise ValueError('Collection archive does not match the Trial and frozen candidate')
    manifest_path = root / 'archive-manifest.json'
    manifest = results.read_json(manifest_path)['files']

    def covered(relative):
        if relative not in manifest:
            raise ValueError('Collection evidence is not covered by the archive: ' + relative)

    for relative in ['summary.json', 'provenance.json', str(runtimes[0].relative_to(root)),
                     str(runtimes[0].parents[1].relative_to(root) / 'result.json')]:
        covered(relative)
    if recipe_error:
        if bundle.get('schemaVersion') != 2 or runtime.get('status') != 'completed' or 'id' in runtime.get('recipe', {}):
            raise ValueError('Archive does not match the v2 recipe label defect')
        recovered = results.collect(root)  # All official task/reward/evidence checks still apply.
        if recovered['task'] != trial['task']:
            raise ValueError('Official result belongs to another Trial task')
        for relative in ['harbor/result.json', str(runtimes[0].parents[1].relative_to(root) / 'lock.json'),
                         *recovered['evidence'].values()]:
            if relative != recovered['evidence']['workspace']:
                covered(relative)
        summary = {**{k: original[k] for k in ['runId', 'runDir', 'wallTimeSeconds', 'cleanup', 'accounting']
                      if k in original}, **recovered}
        reason = 'v2_recipe_label_missing'
    else:
        # There is no official score to recover. Preserve null and identify the platform fault.
        summary = {**original, 'failure': diagnosed, 'stopReason': diagnosed['code'],
                   'scoringStatus': diagnosed['scoringStatus']}
        reason = 'container_transport_diagnosis'
    summary['resultCollection'] = {
        'version': VERSION, 'reason': reason,
        'archiveSha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'originalSummarySha256': manifest['summary.json']['sha256'],
        'collectorSha256': hashlib.sha256(Path(results.__file__).read_bytes()).hexdigest(),
        'diagnosticSha256': hashlib.sha256(Path(failure.__file__).read_bytes()).hexdigest(),
    }
    return summary


def projection(summary):
    """Only result fields; original timing, attempts, accounting and selections stay intact."""
    return {
        'state': 'finished' if summary.get('pipelineStatus') == 'completed' else 'failed',
        'score': summary.get('officialReward'), 'outcome': summary.get('taskOutcome'),
        'failure': summary.get('failure'), 'stopReason': summary.get('stopReason'),
        'scoringStatus': summary.get('scoringStatus', 'completed' if summary.get('officialReward') is not None else 'unknown'),
        'summary': summary, 'taskAssessment': None, 'lastCollectionError': None,
        'resultCollection': summary.get('resultCollection'),
    }
