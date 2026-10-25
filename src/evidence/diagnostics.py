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
        for field in ('candidateDiagnostics','sourceIdentities'):
            if field not in t and index.get(t['id'],{}).get(field):t[field]=index[t['id']][field]
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
        elif state=='collecting': label='结果归集中';scoring='pending'
        elif state in ['reserved', 'queued', 'launching', 'running']: label = '等待启动' if state in ['reserved','queued'] else '运行中，等待评分'; scoring = 'pending'
        else: label = '未评分'
        t['scoringStatus'] = scoring
        summary=t.get('summary') or {}
        recovery=t.get('requestRecovery') or summary.get('requestRecovery') or {}
        if recovery:t['requestRecovery']={**recovery,'failures':[{**public_failure(r),
            **({'recoveredBy':r['recoveredBy']} if r.get('recoveredBy') else {})} for r in recovery.get('failures',[])]}
        bridge=t.get('containerTransport') or summary.get('containerTransport')
        if bridge:t['containerTransport']=bridge
        if failure:
            diagnosis={k:t['failure'][k] for k in ('category','categoryLabel','causeNote')}
        elif finite(t.get('score')) and t['score']==0:
            diagnosis={'category':'task_result','categoryLabel':'正式评分未通过','causeNote':'已取得官方评分，结果未满足任务要求；具体失败条件见评分报告。'}
        else:diagnosis={'category':'none','categoryLabel':'无已确认的最终故障','causeNote':''}
        has_score=scoring=='completed'
        diagnosis['impact']='official_score_recorded' if has_score else scoring
        diagnosis['impactLabel']='已有官方评分，历史故障不会替换该分数' if has_score else '尚无官方评分；任务完成分按活动绑定规则计算'
        t['diagnosis']={'version':'failure-attribution-v1',**diagnosis}
        t['resultLabel'] = label + (' · '+t['failure']['message'] if failure and scoring != 'pending' else '')
        # Report projections may already contain a versioned assessment but omit the raw summary.
        if (t.get('taskAssessment') or {}).get('rule') != rule_for(config):
            t['taskAssessment'] = task_outcome(t, config)
        t['completionLabel'] = t['taskAssessment']['label'] + ('' if rule_for(config)==END_TO_END_RULE else '；官方' + t['resultLabel'])
        results.append(t)
    return results


def candidate_diagnostics(root,summary):
    """Candidate messages are evidence of a report, never official score authority."""
    rows=[]
    for path in sorted(Path(root).glob('harbor/*/phyexp/events.json')):
        if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):continue
        try:events=json.loads(path.read_text())
        except (OSError,ValueError):continue
        if not isinstance(events,list):continue
        for index,event in enumerate(events):
            if not isinstance(event,dict) or event.get('type') not in ('error','request/error'):continue
            value=event.get('data') or event
            if isinstance(value,dict):value=value.get('error') or value
            row=value if isinstance(value,dict) else {'message':str(value)}
            rows.append({'code':str(row.get('code') or row.get('type') or 'candidate_error')[:120],
                'message':str(row.get('message') or row.get('error') or row)[:2000],
                'stage':'candidate-execution','source':'candidate-reported','authority':'diagnostic-only',
                'evidence':path.relative_to(root).as_posix(),'eventIndex':index})
    return rows[-20:]
