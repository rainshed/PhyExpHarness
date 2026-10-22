"""Shared reading projection, including explicitly derived historical diagnoses."""
import json
from pathlib import Path
from src.execution.host.failure import public_failure
from .outcomes import task_outcome, rule_for, END_TO_END_RULE, finite


def trial_diagnostics(trials, data=None, config=None):
    index = {}
    if data:
        file = Path(data)/'failure-diagnoses.json'
        if file.exists(): index = json.loads(file.read_text()).get('trials', {})
    results = []
    for original in trials:
        t = dict(original)
        failure = t.get('failure') or (t.get('summary') or {}).get('failure')
        if not failure and t.get('failureContract') != 'request-failure-v2':
            failure = index.get(t['id'], {}).get('failure')
        if failure:
            t['failure'] = {**public_failure(failure), 'scoringStatus': failure.get('scoringStatus', 'unknown')}
        state = t.get('state')
        scoring = t.get('scoringStatus') or (failure or {}).get('scoringStatus', 'unknown')
        if (rule_for(config)==END_TO_END_RULE and t.get('score') is not None
                and not (finite(t['score']) and t['score'] in (0,1))):label='结果无效，未采信';scoring='unknown'
        elif t.get('score') is not None: label = '评分 '+str(t['score']); scoring = 'completed'
        elif state in ['reserved', 'queued', 'launching', 'running']: label = '等待启动' if state in ['reserved','queued'] else '运行中，等待评分'; scoring = 'pending'
        else: label = '未评分'
        t['scoringStatus'] = scoring
        t['resultLabel'] = label + (' · '+t['failure']['message'] if failure and scoring != 'pending' else '')
        # Report projections may already contain a versioned assessment but omit the raw summary.
        if (t.get('taskAssessment') or {}).get('rule') != rule_for(config):
            t['taskAssessment'] = task_outcome(t, config)
        t['completionLabel'] = t['taskAssessment']['label'] + ('' if rule_for(config)==END_TO_END_RULE else '；官方' + t['resultLabel'])
        results.append(t)
    return results
