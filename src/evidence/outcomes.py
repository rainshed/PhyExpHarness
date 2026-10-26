"""Versioned, read-only task completion assessment. Never rewrites official scores."""
import math
from datetime import datetime

LEGACY_RULE = 'task-completion-v1'
RULE = 'task-completion-v2'
RESOURCE_RULE = 'task-completion-v3'
END_TO_END_RULE = 'task-completion-v4'
DEFAULT_RULE = END_TO_END_RULE
RULES = {LEGACY_RULE, RULE, RESOURCE_RULE, END_TO_END_RULE}
END_TO_END_DESCRIPTION = ('任务成功率：已进入启动尝试且最终结束，官方通过计 1，其余计 0，包含外部故障和结果缺失；'
    '未执行、无先行失败的明确人工取消、运行中及结束状态待核实单列。失败原因与官方原始评分保留；跨任务按所选任务等权。')
LEGACY_DESCRIPTION = ('任务成功率：官方通过计 1，官方未通过、模型输出异常、未提交及约定限额耗尽计 0；'
               '外部故障、取消、待定和待归因单列。官方原始评分不变；跨任务按所选任务等权。')
DESCRIPTION = ('任务成功率：官方通过计 1，官方未通过、模型输出异常、未提交、约定限额耗尽及最终未恢复的模型服务过载或连接故障计 0；'
               '其他外部故障、取消、待定和待归因单列。官方原始评分不变；跨任务按所选任务等权。')
CONNECTION_FAILURES = {'model_service_overloaded', 'model_transport_error', 'model_stream_incomplete'}

def rule_for(config=None):
    rule = (config or {}).get('taskEvaluationRule', LEGACY_RULE)
    if rule not in RULES:
        raise ValueError('Unknown task evaluation rule: ' + str(rule))
    return rule

def description_for(config=None):
    rule=rule_for(config)
    if rule == END_TO_END_RULE:return END_TO_END_DESCRIPTION
    return (DESCRIPTION+' 预算准入不足单列为截断；平台账本和凭证故障单列为外部故障，均不计入任务成功率。') if rule==RESOURCE_RULE else DESCRIPTION if rule==RULE else LEGACY_DESCRIPTION

OUTPUT_FAILURES = {'invalid_tool_arguments', 'tool_argument_schema_error', 'stream_whitespace', 'stream_repetition',
                   'response_size_limit', 'tool_argument_size_limit', 'model_output_limit',
                   'user_stop_invalid_tool_argument_stream'}
EXTERNAL_FAILURES = {'model_service_overloaded', 'model_transport_error', 'model_response_error', 'model_stream_incomplete',
                     'stream_idle_timeout', 'startup_failure', 'verifier_failed', 'archive_invalid',
                     'supervisor_lost_start_not_repeated', 'result_collection_failed', 'container_transport_error',
                     'control_database_busy','control_database_error','control_unavailable','request_auth_failed','request_lease_expired',
                     'log_size_limit','log_record_size_limit','storage_write_error'}
PENDING = {'reserved', 'queued', 'launching', 'running', 'collecting'}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def failure_before_stop(trial, failure):
    """Only positive evidence of a prior failure overrides an operator cancellation."""
    if failure.get('code') in OUTPUT_FAILURES:return True
    if not failure.get('code') or failure['code'] in {'user_stop','request_cancelled','runtime_failed'}:return False
    detected, stopped = failure.get('detectedAt'), trial.get('stopRequestedAt')
    if isinstance(detected,str):
        try:detected=datetime.fromisoformat(detected.replace('Z','+00:00')).timestamp()
        except (ValueError,OverflowError,OSError):return False
    return finite(detected) and finite(stopped) and detected < stopped


def failure_label(reason):
    if reason in OUTPUT_FAILURES:return '模型输出异常'
    if reason in CONNECTION_FAILURES:return '模型连接或服务异常'
    return {'model_response_error':'模型请求失败','stream_idle_timeout':'模型响应停滞','request_timeout':'模型请求超时',
        'startup_failure':'实验启动失败','container_transport_error':'容器桥接异常','verifier_failed':'评分器异常',
        'archive_invalid':'结果归档异常','result_collection_failed':'结果收集异常',
        'supervisor_lost_start_not_repeated':'执行监督中断，结果缺失','runtime_failed':'执行异常','candidate_nonzero_exit':'候选进程异常退出',
        'trial_deadline':'实验时限耗尽','campaign_deadline':'活动时限耗尽','budget_admission_denied':'执行额度不足',
        'accounting_unavailable':'用量账本异常','accounting_lease_expired':'执行凭证到期或撤销',
        'control_database_busy':'控制数据库繁忙','control_database_error':'控制数据库异常',
        'control_unavailable':'模型访问控制不可用','request_auth_failed':'执行凭证异常','request_lease_expired':'执行凭证到期或撤销',
        'storage_capacity':'存储空间不足','storage_write_error':'日志写入失败',
        'log_size_limit':'输出日志容量超限','log_record_size_limit':'单条日志过大',
        'accounting_auth_failed':'执行凭证异常','accounting_protocol_error':'准入接口异常',
        'no_submission':'未提交结果','invalid_submission':'提交无效','request_cancelled':'执行请求取消',
        'invalid_official_result':'官方结果无效'}.get(reason,'结果缺失（原因待查）')


def end_to_end_outcome(trial, summary, failure, result):
    state=trial.get('state');official=trial.get('score')
    # The collector verifies binary official results. Never turn a cleanup error into a loss.
    if finite(official) and official in (0,1):
        return result('passed' if official==1 else 'failed','official_result','official_score',
                      '成功' if official==1 else '失败 · 官方未通过')
    if state not in {'finished','failed','cancelled','unknown'} or (state=='unknown' and not finite(trial.get('finishedAt'))):
        return result('unresolved','process_state_unknown',label='结束状态待核实')
    if not finite(trial.get('startedAt')):
        return result('not_started',failure.get('code') or trial.get('stopReason') or 'not_started',label='未执行')
    code=failure.get('code') or trial.get('stopReason')
    outcome=trial.get('taskOutcome') or trial.get('outcome') or summary.get('taskOutcome')
    explicit_failure=(code in OUTPUT_FAILURES or outcome in {'no_submission','invalid_submission'}
                      or failure_before_stop(trial,failure))
    if (trial.get('stopReason')=='user_stop' or code=='user_stop') and not explicit_failure:
        return result('cancelled','user_stop',label='已取消 · 人工停止')
    reason=code or outcome or ('invalid_official_result' if official is not None else 'missing_result')
    return result('failed',reason,label='失败 · '+failure_label(reason))


def task_outcome(trial, config=None):
    rule = rule_for(config)
    summary = trial.get('summary') or {}
    failure = trial.get('failure') or summary.get('failure') or {}
    code = failure.get('code') or trial.get('stopReason')
    state = trial.get('state')
    official = trial.get('score')

    def result(category, reason, basis='rule', label=None):
        score = 1 if category == 'passed' else 0 if category == 'failed' else None
        labels = {'passed': '任务完成分 1', 'failed': '任务完成分 0', 'external_failure': '外部故障，不计入任务成功率',
                  'cancelled': '已取消，不计入任务成功率', 'pending': '任务结果待定', 'unresolved': '待归因，不自动判零'}
        return {'rule': rule, 'category': category, 'score': score, 'included': score is not None,
                'reason': reason, 'basis': basis, 'label': label if label is not None else labels[category]}

    if state in PENDING:
        return result('pending', 'in_progress')
    if rule == END_TO_END_RULE:
        return end_to_end_outcome(trial, summary, failure, result)
    # A trustworthy recorded official result takes precedence over subsequent cleanup errors.
    if finite(official):
        return result('passed' if official == 1 else 'failed', 'official_result', 'official_score')
    if state == 'unknown':
        return result('unresolved', code or 'process_state_unknown')
    if rule == RESOURCE_RULE:
        if code=='budget_admission_denied':return result('cancelled',code)
        if code in {'accounting_unavailable','accounting_lease_expired','accounting_auth_failed','accounting_protocol_error'}:return result('external_failure',code)
    if rule in {RULE,RESOURCE_RULE} and code in CONNECTION_FAILURES:
        if state == 'cancelled' or trial.get('stopReason') in {'user_stop', 'request_cancelled', 'campaign_deadline'}:
            return result('cancelled', trial.get('stopReason') or 'cancelled')
        return result('failed', code)
    if code in OUTPUT_FAILURES:
        return result('failed', code)
    if code in EXTERNAL_FAILURES:
        return result('external_failure', code)
    if code == 'request_timeout':
        if failure.get('observed', {}).get('responseBytes') == 0:
            return result('unresolved', 'request_timeout_without_response')
        return result('failed', code)
    if code == 'trial_deadline':
        # A late launch can get less than the promised single-trial budget.
        expected = trial.get('taskTimeLimitSeconds') or (summary.get('runtime') or {}).get('recipe', {}).get('agentTimeoutSec')
        if not finite(expected):
            return result('unresolved', 'unverified_trial_budget')
        start, deadline = trial.get('startedAt'), trial.get('deadline')
        if finite(start) and finite(deadline) and deadline - start >= expected - 1:
            return result('failed', 'trial_time_limit')
        return result('cancelled', 'shortened_trial_budget')
    if code in {'user_stop', 'request_cancelled', 'campaign_deadline'} or state == 'cancelled':
        return result('cancelled', code or 'cancelled')
    outcome = trial.get('taskOutcome') or trial.get('outcome') or summary.get('taskOutcome')
    if outcome in {'no_submission', 'invalid_submission'} or code in {'no_submission', 'invalid_submission'}:
        return result('failed', outcome or code)
    if (summary.get('pipelineStatus') == 'completed' and summary.get('submissionPresent') is False
            and not code and trial.get('scoringStatus') != 'failed'):
        return result('failed', 'no_submission')
    return result('unresolved', code or 'missing_result')


def outcome_summary(trials, tasks=None, config=None):
    """Every attempt remains visible; no pooling advantage from oversampling easy tasks."""
    rule = rule_for(config)
    rows = [(t, t['taskAssessment'] if (t.get('taskAssessment') or {}).get('rule') == rule else task_outcome(t, config)) for t in trials]

    def count(selected):
        counts = {key: sum(o['category'] == key for _, o in selected)
                  for key in ['passed', 'failed', 'external_failure', 'cancelled', 'pending', 'unresolved'] + (['not_started'] if rule==END_TO_END_RULE else [])}
        eligible = counts['passed'] + counts['failed']
        official = [t['score'] for t, _ in selected if finite(t.get('score')) and t.get('state') not in PENDING
                    and (rule!=END_TO_END_RULE or t['score'] in (0,1))]
        conservative = eligible + (counts['unresolved'] if rule!=END_TO_END_RULE else 0)
        return {'attempts': len(selected), **counts, 'eligible': eligible,
                'derivedFailures': sum(o['category'] == 'failed' and o['basis'] == 'rule' for _, o in selected),
                'successRate': counts['passed'] / eligible if eligible else None,
                'conservativeSuccessRate': counts['passed'] / conservative if conservative else None,
                'officialScored': len(official), 'officialMean': sum(official) / len(official) if official else None}

    tasks = list(tasks if tasks is not None else dict.fromkeys(t.get('task') for t in trials))
    by_task = {task: count([(t, o) for t, o in rows if t.get('task') == task]) for task in tasks}
    rates = [r['successRate'] for r in by_task.values()]
    return {'rule': rule, 'description': description_for(config), 'total': count(rows), 'byTask': by_task,
            'coveredTasks': sum(r is not None for r in rates), 'taskCount': len(tasks),
            'macroSuccessRate': sum(rates) / len(rates) if rates and all(r is not None for r in rates) else None}


def evaluation(trials, tasks, candidates=(), config=None):
    return {**outcome_summary(trials, tasks, config), 'byCandidate': {
        c['id']: outcome_summary([t for t in trials if t.get('candidateId') == c['id']], tasks, config)
        for c in candidates}}
