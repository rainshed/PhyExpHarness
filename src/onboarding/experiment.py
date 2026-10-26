"""Bounded first-activity operator client with durable, replayable request identities."""
import hashlib
import json
import math
import re
import time
import uuid
from pathlib import Path

from .api import API, health_matches
from .common import Problem, locked, read_json, write_json


def session_path(config, name):
    if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', name):
        raise Problem('invalid_session', 'session 须为 1–64 个字母、数字、下划线或连字符，首位须为字母或数字。', exit_code=2)
    return Path(config['data_dir'])/'onboarding/experiments'/(name+'.json')


def client(config):
    api = API(config, timeout=120)
    if not health_matches(api.request('/health'), config):
        raise Problem('different_instance', '后台身份与当前路径配置不一致。', '核对 status 与数据目录。')
    return api


def catalog(config):
    api = client(config)
    models = api.request('/models')
    credentials = {p['id']: p.get('credential', {}).get('state', 'unknown') for p in api.request('/providers')['providers']}
    return {'status': 'passed', **models, 'credentialStates': credentials, 'modelRequests': 0}


def tasks(config):
    return {'status': 'passed', **client(config).request('/tasks'), 'modelRequests': 0}


def selected_model(catalogue, selection, effort):
    provider, model = selection
    entry = next((row for row in catalogue['models'] if row['provider'] == provider and row['model'] == model), None)
    if entry is None:
        raise Problem('model_unavailable', f'模型不在当前目录中：{provider}/{model}', '运行 models；按模型指南配置后选择准确 ID。')
    efforts = entry['reasoningEfforts']
    effort = effort if effort is not None else entry.get('defaultReasoningEffort')
    if effort is not None and effort not in efforts:
        raise Problem('invalid_reasoning', f'模型不支持推理等级：{effort}')
    return {'provider': provider, 'model': model, **({'reasoningEffort': effort} if effort is not None else {})}


def initialize(config, name, *, solver, meta, task, wall_time=None, solver_effort=None, meta_effort=None):
    path = session_path(config, name)
    inputs = {'solver': list(solver), 'meta': list(meta), 'task': task, 'wallTimeSeconds': wall_time, 'solverEffort': solver_effort, 'metaEffort': meta_effort}
    with locked(path.with_suffix('.lock')):
        existing = read_json(path)
        if existing:
            if existing.get('inputs') != inputs:
                raise Problem('session_config_changed', '同名 session 已绑定其他配置。', '查询原 session；有意开始另一实验时使用新的明确名称。')
            return {'status': 'passed', 'session': name, 'sessionFile': str(path), 'config': existing['config'], 'reused': True, 'modelRequests': 0}
        api = client(config)
        catalogue = api.request('/models')
        timing = next((t for t in api.request('/tasks')['tasks'] if t['id'] == task), None)
        if not timing or timing.get('unavailable'):
            raise Problem('task_unavailable', '所选任务不存在或无法读取时限。', '运行 tasks 并核对 Quantum-Harbor。')
        required = timing.get('requiredTimeSeconds')
        bounded = isinstance(required, (int, float)) and math.isfinite(required) and required > 0
        if wall_time is None and not bounded:
            raise Problem('unbounded_task', 'benchmark 未设置有限阶段上限，请用 --wall-time 明确活动时间。')
        seconds = wall_time if wall_time is not None else math.ceil(required+1800)
        if type(seconds) is not int or seconds <= 0:
            raise Problem('invalid_time', '活动时间必须是正整数秒。')
        value = {'name': '首次实验 · '+name,
                 'objective': '完成一次可核验的首次实验：优先使用已准备的 H0，在所选公开任务上安排一次实验（允许短窗口尝试，遵守活动硬截止），读取官方评分与证据后提交总结。明确区分工程链路、任务得分和科学结论；不声称一次尝试证明泛化收益。',
                 'solver': selected_model(catalogue, solver, solver_effort), 'meta': selected_model(catalogue, meta, meta_effort),
                 'tasks': [task], 'concurrency': 1, 'maxTrials': 1, 'maxRounds': 1, 'wallTimeSeconds': seconds,
                 'reserveSeconds': None, 'stopMode': 'strict', 'drainGraceSeconds': 0, 'retries': 0,
                 'resourcePolicy': 'meta-resource-planning-v1'}
        receipt = {'schemaVersion': 1, 'session': name, 'inputs': inputs, 'config': value, 'benchmark': timing,
                   'createRequest': {'config': value, 'idempotencyKey': str(uuid.uuid4()), 'modelCatalogRevision': catalogue['revision']},
                   'createdAt': time.time()}
        write_json(path, receipt)
        return {'status': 'passed', 'session': name, 'sessionFile': str(path), 'config': value,
                'benchmarkReservationSeconds': required, 'modelRequests': 0, 'nextStep': '核对配置后运行 experiment prepare；只有 experiment start 会启动真实模型工作。'}


def load_session(path):
    receipt = read_json(path)
    if not receipt or receipt.get('schemaVersion') != 1 or not isinstance(receipt.get('createRequest'), dict):
        raise Problem('session_missing', '没有有效的首次实验 session。', '先运行 experiment init；保留损坏的原回执供核对。')
    if receipt['createRequest'].get('config') != receipt.get('config'):
        raise Problem('session_modified', '本地配置与创建请求不一致。', '不要编辑已提交的 session；先核对后台活动。')
    return receipt


def preparation(detail):
    operations = [o for o in detail.get('operations', []) if o.get('kind') == 'prepare_h0']
    if not operations:
        return 'pending'
    state = max(operations, key=lambda o: o.get('startedAt', 0))['state']
    if state == 'failed':
        return 'failed'
    return 'ready' if state == 'finished' and detail.get('candidates') else 'pending'


def prepare(config, name):
    path = session_path(config, name)
    with locked(path.with_suffix('.lock')):
        receipt = load_session(path)
        api = client(config)
        if not receipt.get('campaignId'):
            # The request was persisted by init before any creation can be sent.
            # Replays intentionally use the original catalog revision and body.
            result = api.request('/campaigns', receipt['createRequest'])
            receipt['campaignId'] = result['id']
            write_json(path, receipt)
        detail = api.request('/campaigns/'+receipt['campaignId'])
        state = preparation(detail)
        return {'status': 'passed' if state == 'ready' else 'failed' if state == 'failed' else 'pending',
                'session': name, 'campaignId': receipt['campaignId'], 'preparation': state, 'modelRequests': 0,
                'workbenchUrl': config['ui_url']+'/#phyexp/'+receipt['campaignId'],
                'operations': detail.get('operations', []),
                'nextStep': '用相同 session 再次 prepare 查询准备结果；准备完成后显式 start。'}


def start_experiment(config, name):
    path = session_path(config, name)
    with locked(path.with_suffix('.lock')):
        receipt = load_session(path)
        if not receipt.get('campaignId'):
            raise Problem('not_prepared', '尚未创建活动。', '先运行 experiment prepare。')
        api = client(config)
        route = '/campaigns/'+receipt['campaignId']
        detail = api.request(route)
        if detail.get('startedAt') is not None:
            return {'status': 'passed', 'campaignId': detail['id'], 'campaignState': detail['state'], 'reused': True,
                    'nextStep': '活动已启动过；使用 experiment status/wait 查看，不会再次启动。'}
        if detail['state'] != 'draft' or preparation(detail) != 'ready':
            raise Problem('not_ready', '活动尚未准备完成或已进入其他状态。', '查询 experiment status/prepare 与准备日志。', exit_code=3)
        credentials = {p['id']: p.get('credential', {}).get('state') for p in api.request('/providers')['providers']}
        missing = [role for role in ('solver', 'meta') if credentials.get(receipt['config'][role]['provider']) != 'configured']
        if missing:
            raise Problem('credential_missing', '模型认证缺失或已过期：'+', '.join(missing), '按模型指南完成认证，再用相同 session 启动。')
        if not receipt.get('startRequest'):
            receipt['startRequest'] = {'action': 'start', 'expectedRevision': detail['revision'], 'idempotencyKey': str(uuid.uuid4())}
            write_json(path, receipt)
        try:
            result = api.request(route+'/control', receipt['startRequest'])
        except Problem as error:
            # A definitive revision conflict proves this request was not accepted.
            # A timeout does not: it must retain exactly the same request.
            if error.code == 'http_409':
                latest = api.request(route)
                if latest.get('startedAt') is None and latest['state'] == 'draft':
                    receipt.pop('startRequest', None); write_json(path, receipt)
            raise
        receipt['startedAt'] = result.get('startedAt')
        write_json(path, receipt)
        return {'status': 'passed', 'session': name, 'campaignId': receipt['campaignId'], 'campaignState': result['state'],
                'workbenchUrl': config['ui_url']+'/#phyexp/'+receipt['campaignId'],
                'nextStep': '真实模型工作已启动；用 experiment status/wait 查询。关闭本地命令不取消活动。'}


def verified_sources(trial, data_dir):
    """Verify readability and existing official digests; never compute another score."""
    output = Path(trial.get('output', ''))
    if not output.is_absolute() or not output.resolve().is_relative_to(Path(data_dir).resolve()):
        return False, []
    sources = trial.get('officialResult', {}).get('sources', {})
    selected = [(name, digest) for name, digest in sources.items() if name.endswith(('/verifier/reward.txt', '/verifier/artifacts/score_report.json'))]
    if len(selected) != 2:
        return False, []
    paths = []
    for name, digest in selected:
        file = output/name
        if file.is_symlink() or not file.resolve().is_relative_to(output.resolve()):
            return False, []
        try:
            if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                return False, []
        except OSError:
            return False, []
        paths.append(str(file))
    return True, paths


def assessment(detail, config):
    trials = []
    for trial in detail.get('trials', []):
        valid, paths = verified_sources(trial, config['data_dir'])
        complete = (trial.get('state') == 'finished' and trial.get('scoringStatus') == 'completed'
                    and trial.get('score') is not None and trial.get('officialResult', {}).get('status') == 'available'
                    and trial.get('evidenceIndex', {}).get('state') == 'complete'
                    and trial.get('evidenceStatus', {}).get('status') == 'complete' and valid)
        trials.append({k: trial.get(k) for k in ('id', 'state', 'task', 'score', 'scoringStatus', 'failure', 'evidenceIndex')} |
                      {'verifiedOfficialFiles': paths, 'acceptance': 'passed' if complete else 'incomplete'})
    success = any(t['acceptance'] == 'passed' for t in trials)
    settled = detail['state'] in ('finished', 'failed') and not any(j['state'] in ('running', 'queued', 'retry') for j in detail.get('backgroundWork', []))
    blocked = (detail.get('metaStatus') or {}).get('state') == 'needs_attention' or preparation(detail) == 'failed'
    return {'status': 'passed' if settled and success and detail['state'] == 'finished' else 'failed' if settled or blocked else 'pending',
            'campaignId': detail['id'], 'campaignState': detail['state'], 'trialAcceptance': 'passed' if success else 'incomplete',
            'trials': trials, 'backgroundWork': detail.get('backgroundWork', []), 'metaStatus': detail.get('metaStatus'),
            'metaQuestions': detail.get('metaQuestions', []),
            'workbenchUrl': config['ui_url']+'/#phyexp/'+detail['id'],
            'nextStep': '在工作台核对活动、官方评分与证据。零分与链路验收分开；未评分不算通过。'}


def experiment_status(config, name):
    receipt = load_session(session_path(config, name))
    if not receipt.get('campaignId'):
        return {'status': 'pending', 'session': name, 'config': receipt['config'], 'nextStep': '尚未确认创建；使用相同 session 运行 prepare。'}
    detail = client(config).request('/campaigns/'+receipt['campaignId'])
    return assessment(detail, config)


def wait(config, name, timeout=30):
    if not 1 <= timeout <= 60:
        raise Problem('invalid_wait', '单次等待为 1–60 秒，可重复执行同一命令。', exit_code=2)
    deadline = time.monotonic()+timeout
    while True:
        result = experiment_status(config, name)
        if result['status'] != 'pending' or time.monotonic() >= deadline:
            return result
        time.sleep(min(2, max(0, deadline-time.monotonic())))
