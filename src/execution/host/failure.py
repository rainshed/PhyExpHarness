"""Failure facts from execution artifacts, independent of platform state.

Never replace a scientific score or infer token usage from output length.
Only fixed descriptions and safe metadata leave this module; raw errors stay archived.
"""
import json
from pathlib import Path

MESSAGES = {
    'budget_admission_denied': '当前额度不足以准入下一次模型请求',
    'accounting_unavailable': '平台用量账本暂时不可用',
    'control_database_busy': '平台控制数据库暂时繁忙',
    'control_database_error': '平台控制数据库异常',
    'control_unavailable': '平台模型访问控制暂时不可用',
    'request_auth_failed': '平台请求凭证验证失败',
    'request_lease_expired': '平台请求凭证到期或撤销',
    'accounting_lease_expired': '平台请求凭证已到期或被撤销',
    'accounting_auth_failed': '平台请求凭证验证失败',
    'accounting_protocol_error': '平台准入接口返回异常',
    'invalid_tool_arguments': '工具调用参数格式异常，无法构成合法 JSON',
    'stream_whitespace': '工具调用参数持续输出空白，触发异常流保护',
    'stream_repetition': '工具调用参数持续重复，触发异常流保护',
    'response_size_limit': '单次模型响应超过本地字节上限',
    'tool_argument_size_limit': '工具调用参数超过本地字节上限',
    'request_timeout': '单次模型请求达到时间上限',
    'stream_idle_timeout': '模型连接长时间没有返回数据',
    'model_output_limit': '模型输出达到提供方上限，执行未正常完成',
    'model_transport_error': '模型请求传输失败',
    'model_service_overloaded': '模型服务暂时不可用或过载',
    'model_response_error': '模型提供方返回错误',
    'model_stream_incomplete': '模型响应缺少完整结束回执',
    'request_cancelled': '模型请求已取消',
    'startup_failure': '实验启动失败',
    'supervisor_lost_start_not_repeated': '单次执行监督进程丢失，未自动重复启动',
    'user_stop': '用户终止了本次实验',
    'user_stop_invalid_tool_argument_stream': '工具参数异常输出后，由用户终止',
    'trial_deadline': '单次实验达到截止时间',
    'campaign_deadline': '活动达到截止时间',
    'verifier_failed': '官方评分器执行失败',
    'runtime_failed': '执行进程未正常完成，具体原因尚未确认',
    'result_collection_failed': '官方评分已完成，但平台收集结果失败',
    'container_transport_error': '容器工具桥接异常，官方评分未完成',
    'environment_start_timeout': '容器环境未在任务启动时限内就绪',
    'environment_healthcheck_failed': '容器环境健康检查失败',
    'environment_container_exited': '容器在环境准备期间提前退出',
    'environment_start_failed': '容器环境准备失败',
    'environment_start_interrupted': '容器环境准备被中断',
    'storage_capacity': '存储空间达到保护线，已保留捕获内容并停止生产者',
    'storage_capacity_wait': '正在等待存储空间恢复',
    'log_size_limit': '输出日志达到显式容量上限，已保留捕获内容',
    'log_record_size_limit': '单条日志超过可处理大小，已保留此前内容',
    'storage_write_error': '日志写入失败，请检查存储状态与文件权限',
    'archive_invalid': '结果或归档未通过完整性检查',
    'unknown_failure': '实验未正常完成，具体原因尚未确认',
}


def failure_attribution(code):
    """Observed layer only; output symptoms do not prove a model-weight defect."""
    if code in {'invalid_tool_arguments','stream_whitespace','stream_repetition','response_size_limit',
                'tool_argument_size_limit','model_output_limit','user_stop_invalid_tool_argument_stream'}:
        return {'category':'model_output','categoryLabel':'模型输出链路',
                'causeNote':'输出格式、内容或大小触发保护；模型与适配器的具体责任仍需原始证据确认。'}
    if code in {'model_transport_error','model_service_overloaded','model_response_error','model_stream_incomplete','stream_idle_timeout'}:
        return {'category':'model_service','categoryLabel':'模型服务或连接',
                'causeNote':'请求服务或传输异常，不作为模型解题能力的直接证据。'}
    if code in {'startup_failure','verifier_failed','archive_invalid','supervisor_lost_start_not_repeated',
                'result_collection_failed','container_transport_error','control_database_busy','control_database_error','control_unavailable',
                'request_auth_failed','request_lease_expired','storage_capacity','storage_capacity_wait',
                'log_size_limit','log_record_size_limit','storage_write_error'} or code.startswith(('environment_','accounting_')):
        return {'category':'platform','categoryLabel':'平台执行或控制',
                'causeNote':'平台、执行环境或评分流程出现异常。'}
    if code in {'request_timeout','trial_deadline','campaign_deadline','budget_admission_denied','request_cancelled','user_stop'}:
        return {'category':'execution_limit','categoryLabel':'运行限额或停止',
                'causeNote':'按约定时间、资源或停止请求结束。'}
    return {'category':'unknown','categoryLabel':'原因待确认','causeNote':'现有记录不足以确定故障层。'}


def container_transport(root):
    files=list(Path(root).glob('harbor/*/phyexp/container-transport.json'))
    if len(files)!=1:return None
    value=read(files[0])
    if value.get('schemaVersion')!=1:return None
    # Raw exception messages remain in the archive, not public diagnostics.
    keys=('callId','stage','executionState','blocksVerification','time','recoveredBy')
    return {'schemaVersion':1,'verificationBlocked':value.get('verificationBlocked',True),
            'issues':[{k:item[k] for k in keys if k in item} for item in value.get('issues',[])],
            'evidence':str(files[0].relative_to(root))}


def read(path):
    try: return json.loads(Path(path).read_text())
    except (OSError, ValueError): return {}


def public_failure(value):
    code = value.get('code', 'unknown_failure')
    if code not in MESSAGES: code = 'unknown_failure'
    result = {'schemaVersion': 1, 'code': code, 'stage': value.get('stage', 'execution'),
              'message': MESSAGES[code], 'source': value.get('source', 'execution-artifacts'),**failure_attribution(code)}
    if code == 'model_response_error' and (value.get('observed') or {}).get('providerCode') == 'CONTEXT_WINDOW_EXCEEDED':
        result['message'] = '模型适配器判定上下文容量超限，请检查上下文压缩'
    for key in ['requestId', 'detectedAt', 'policyVersion', 'termination', 'evidence', 'observed', 'limits', 'secondaryCodes']:
        if key in value: result[key] = value[key]
    return result


def environment_failure(root, trial, trial_file):
    if trial.get('verifier_result'):
        return None  # A startup receipt cannot invalidate an official score.
    exception = trial.get('exception_info') or {}
    records = sorted(root.glob('harbor/*/phyexp/environment-startup-*.json'))
    for file in records:
        record = read(file)
        code = record.get('code', '')
        if record.get('status') == 'failed' and code.startswith('environment_') and code in MESSAGES:
            if exception.get('exception_type') == 'EnvironmentStartTimeoutError':
                code = 'environment_start_timeout'  # Harbor's outer timer cancels start().
            return {'code': code, 'stage': 'environment', 'evidence': str(file.relative_to(root)),
                    'scoringStatus': 'failed' if record.get('role') == 'verifier' else 'not_run'}
    # Compatibility with Harbor's typed timeout and old wrapper receipts, without
    # rewriting archives or treating every pre-agent collector error as startup.
    code = None
    if exception.get('exception_type') == 'EnvironmentStartTimeoutError':
        code = 'environment_start_timeout'
    elif trial.get('environment_setup') and not trial.get('agent_execution'):
        message = exception.get('exception_message', '')
        for text, cause in [('Compose containers did not become ready', 'environment_start_timeout'),
                            ('Container failed its healthcheck:', 'environment_healthcheck_failed'),
                            ('Container exited during startup:', 'environment_container_exited')]:
            if text in message:
                code = cause
                break
    if code:
        return {'code': code, 'stage': 'environment', 'evidence': str(trial_file.relative_to(root)),
                'scoringStatus': 'failed' if trial.get('agent_execution') else 'not_run'}
    return None


def diagnose(run_dir, stop_reason=None):
    root = Path(run_dir)
    runtimes = sorted(root.glob('harbor/*/phyexp/runtime-summary.json'))
    runtime_file = runtimes[0] if len(runtimes) == 1 else None
    runtime = read(runtime_file) if runtime_file else {}
    trial_files = sorted(root.glob('harbor/*/result.json'))
    trial = read(trial_files[0]) if len(trial_files) == 1 else {}
    verifier = trial.get('verifier_result')
    exception = trial.get('exception_info') or {}
    scoring = 'failed' if 'Verifier' in exception.get('exception_type', '') else ('completed' if verifier else 'unknown')
    result = None
    if runtime_file:
        failure_file = runtime_file.with_name('failure.json')
        stored = read(failure_file)
        if runtime.get('failureContract') == 'request-failure-v2':
            raw = runtime.get('failure')
        elif stored.get('failureContract') == 'request-failure-v2':
            raw = stored.get('failure')
        else:
            raw = stored or runtime.get('failure')
        if raw:
            result = public_failure(raw)
            result['evidence'] = str(failure_file.relative_to(root)) if failure_file.exists() else str(runtime_file.relative_to(root))
        if not result:
            reason = runtime.get('turnEnd') or {}
            code = 'model_output_limit' if reason.get('kind') == 'max-tokens' else None
            error = reason.get('error') or {}
            if reason.get('kind') == 'error':
                code = 'model_transport_error' if error.get('code') == 'TRANSPORT' or 'fetch failed' in error.get('message', '') else 'model_response_error'
            if code: result = public_failure({'code': code, 'stage': 'model', 'evidence': str(runtime_file.relative_to(root))})
    stop = stop_reason or read(root/'process.json').get('stopReason') or read(root/'summary.json').get('stopReason')
    if not verifier and scoring != 'failed' and runtime and (runtime.get('status') == 'error' or runtime.get('error') or result):
        scoring = 'not_run'
    if result and result['code'] in ['request_cancelled', 'runtime_failed'] and stop in MESSAGES:
        result = {**result, **public_failure({**result, 'code': stop})}
    if not result and (stop not in MESSAGES or stop == 'runtime_failed'):
        environment = environment_failure(root, trial, trial_files[0] if len(trial_files) == 1 else None)
        if environment:
            result = public_failure(environment)
            scoring = environment['scoringStatus']
    if not result:
        bridge_error = (exception.get('exception_type') == 'RuntimeError'
                        and exception.get('exception_message', '').startswith('Container transport failed: '))
        code = (stop if stop in MESSAGES and stop != 'runtime_failed' else 'verifier_failed' if scoring == 'failed'
                else 'container_transport_error' if bridge_error
                else 'result_collection_failed' if runtime.get('status') == 'completed' and scoring == 'completed'
                else 'runtime_failed' if runtime else 'unknown_failure')
        if bridge_error and not verifier: scoring = 'not_run'
        result = public_failure({'code': code, 'stage': 'collection' if code == 'result_collection_failed' else 'verifier' if scoring == 'failed' else 'model' if code.startswith('model_') else 'execution',
                                 'evidence': str(trial_files[0].relative_to(root)) if bridge_error else str(runtime_file.relative_to(root)) if runtime_file else 'summary.json'})
    if stop in MESSAGES: result['termination'] = stop
    result['scoringStatus'] = scoring
    # Distinguish causal failure from cleanup/collector errors without exposing raw text.
    result['secondaryCodes'] = list(dict.fromkeys(result.get('secondaryCodes', []) +
        (['runtime_exit'] if runtime.get('error') else []) + (['harbor_exception'] if exception else [])))
    return result


def failed_result(run_dir, error, stop_reason=None):
    failure = diagnose(run_dir, stop_reason)
    if failure['code'] == 'unknown_failure' and isinstance(error, (ValueError, FileNotFoundError)):
        failure = {**failure, **public_failure({'code': 'archive_invalid', 'stage': 'collection'}), 'scoringStatus': failure['scoringStatus']}
    runtime_files = list(Path(run_dir).glob('harbor/*/phyexp/runtime-summary.json'))
    runtime = read(runtime_files[0]) if len(runtime_files) == 1 else {}
    return {'status': 'infrastructure_error', 'pipelineStatus': 'failed', 'officialReward': None,
            'sciencePassed': None, 'error': str(error), 'stopReason': stop_reason or failure['code'],
            'failure': failure, 'scoringStatus': failure['scoringStatus'],
            'containerTransport':container_transport(run_dir),
            **({k:runtime.get(k) for k in ['failureContract','requestRecovery']} if runtime.get('failureContract') else {}),
            'usage': runtime.get('usage', {}), 'accounting': runtime.get('accounting', {})}
