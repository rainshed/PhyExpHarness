"""Local process launch and identity checks. Activity lifecycle remains in control."""
import html
import http.cookiejar
import json
import os
import re
import signal
import socket
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, build_opener

from .api import API, health_matches
from .common import ROOT, Problem, locked, probe, python_path, read_json, write_json
from .install import doctor


def process_identity(pid):
    if type(pid) is not int or pid <= 0:
        return None
    result = probe(['ps', '-p', str(pid), '-o', 'lstart='], timeout=5)
    return result.stdout.strip() if result.returncode == 0 else None


def alive(record):
    if not record or not record.get('identity') or process_identity(record.get('pid')) != record['identity']:
        return False
    command = probe(['ps', '-p', str(record['pid']), '-o', 'command='], timeout=5)
    return bool(record.get('marker') and record['marker'] in command.stdout)


def port_open(port):
    with socket.socket() as connection:
        connection.settimeout(.25)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def launch(command, config, log_path):
    env = dict(os.environ)
    env.update(PHYEXP_DATA_DIR=config['data_dir'], PHYEXP_CONTROL_URL=config['control_url'], PHYEXP_UI_PORT=str(config['ui_port']),
               PHYEXP_UI_PUBLIC_URL='', PHYEXP_UI_HOME=str(Path(config['data_dir'])/'ui'))
    env.pop('PHYEXP_USER_TOKEN', None)
    env['PATH'] = str(python_path(Path(config['source'])).parent)+os.pathsep+env.get('PATH', '')
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as log:
        process = subprocess.Popen(command, cwd=config['source'], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    # Python on macOS can replace its launcher executable while keeping arguments.
    # Match start time and owned arguments, rather than the transient executable.
    identity = None
    marker = ' '.join(command[1:])
    for _ in range(20):
        identity = process_identity(process.pid)
        current = probe(['ps', '-p', str(process.pid), '-o', 'command='], timeout=5)
        if identity and marker in current.stdout:
            break
        if process.poll() is not None:
            break
        time.sleep(.05)
    return {'pid': process.pid, 'identity': identity, 'marker': marker, 'log': str(log_path)}


def login_url(record, config):
    if not record or not alive(record):
        return None
    try:
        content = Path(record['log']).read_text()
    except OSError:
        return None
    matches = re.findall(r'dsh web: (https?://[^\s\x1b]+)', content)
    if not matches:
        return None
    value = matches[-1]
    parsed = urlsplit(value)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.port != config['ui_port'] or parsed.username or parsed.password:
        return None
    return value


def ui_ready(record, config):
    url = login_url(record, config)
    if not url:
        return False
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        with opener.open(url, timeout=2) as response:
            response.read(1024)
        with opener.open(config['ui_url']+'/phyexp/api/health', timeout=2) as response:
            return health_matches(json.load(response), config)
    except (OSError, ValueError):
        return False


def status(config):
    directory = Path(config['data_dir'])/'onboarding'
    state = read_json(directory/'processes.json', {})
    try:
        health = API(config, timeout=2).request('/health')
        control = 'ready' if health_matches(health, config) else 'different_instance'
    except Problem:
        control = 'unavailable'
    ui = 'ready' if state.get('config') == config and ui_ready(state.get('ui'), config) else 'unavailable'
    return {'status': 'passed' if control == ui == 'ready' else 'pending',
            'control': control, 'ui': ui, 'controlUrl': config['control_url'], 'workbenchUrl': config['ui_url'],
            'dataDir': config['data_dir'], 'processes': {name: {**{k:record[k] for k in ('pid', 'log') if k in record}, 'alive': alive(record)} for name, record in state.items() if name in ('control', 'ui')},
            'loginFile': str(directory/'login.html'), 'nextStep': '用 start --open 或本地 login.html 打开研究工作台。'}


def start(config, *, timeout=60, open_browser=False, root=ROOT):
    directory = Path(config['data_dir'])/'onboarding'
    with locked(directory/'start.lock'):
        prior = read_json(directory/'processes.json', {})
        if prior.get('config') != config and any(alive(prior.get(role)) for role in ('control', 'ui')):
            raise Problem('live_configuration_changed', '已有本地进程使用不同配置。', '用 status 核对；停止并确认旧进程后再更改路径或端口。')
        state = prior if prior.get('config') == config else {'config': config}
        checks = doctor(config, project_only=True, root=root)
        if checks['status'] != 'passed':
            return checks
        if not config['quantum_harbor'] or not (Path(config['quantum_harbor'])/'harbor_tasks').is_dir():
            raise Problem('harbor_missing', '需要有效 Quantum-Harbor checkout。', '传入 --quantum-harbor；先按外部任务指南准备。')
        api = API(config, timeout=2)
        def control_ready():
            try:
                return health_matches(api.request('/health'), config)
            except Problem:
                return False
        if port_open(config['control_port']) and not control_ready():
            raise Problem('control_port_busy', '后台端口已被其他实例占用或认证不匹配。', '核对 status、数据目录和端口；不会终止未知进程。')
        if port_open(config['ui_port']) and not alive(state.get('ui')):
            raise Problem('ui_port_busy', '工作台端口已被未知进程占用。', '选择空闲 --ui-port 或核对原进程。')
        write_json(directory/'local.json', config)
        if not control_ready() and not alive(state.get('control')):
            command = [str(python_path(root)), '-m', 'src.control.server', '--data-dir', config['data_dir'], '--quantum-harbor', config['quantum_harbor'], '--port', str(config['control_port'])]
            if config['model_config']:
                command += ['--model-config', config['model_config']]
            state['control'] = launch(command, config, directory/'control.log')
            write_json(directory/'processes.json', state)
        deadline = time.monotonic()+timeout
        while not control_ready():
            if not alive(state.get('control')):
                raise Problem('control_exited', '后台在就绪前退出。', f'查看 {directory / "control.log"}')
            if time.monotonic() >= deadline:
                raise Problem('control_start_pending', '后台启动尚未确认，已保留进程。', '用相同参数运行 status/start，查看 control.log。', exit_code=3)
            time.sleep(.25)
        if not alive(state.get('ui')):
            state['ui'] = launch(['node', str(root/'scripts/workbench.mjs')], config, directory/'workbench.log')
            write_json(directory/'processes.json', state)
        deadline = time.monotonic()+timeout
        while not ui_ready(state.get('ui'), config):
            if not alive(state.get('ui')):
                raise Problem('ui_exited', '工作台在就绪前退出；后台保持运行。', f'查看 {directory / "workbench.log"}')
            if time.monotonic() >= deadline:
                raise Problem('ui_start_pending', '工作台启动尚未确认，已保留进程。', '用相同参数运行 status/start，查看 workbench.log。', exit_code=3)
            time.sleep(.25)
        url = login_url(state['ui'], config)+'#phyexp'
        login = directory/'login.html'
        fd = os.open(login, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write('<!doctype html><meta charset="utf-8"><title>PhyExpHarness 登录</title><a href="'+html.escape(url, quote=True)+'">打开本机研究工作台</a>')
        result = status(config)
        result['browserOpened'] = bool(open_browser and webbrowser.open(url))
        return result


def stop_local(config):
    """Only stop owned local processes when the backend confirms no active work."""
    directory = Path(config['data_dir'])/'onboarding'
    with locked(directory/'start.lock'):
        state = read_json(directory/'processes.json', {})
        if state.get('config') != config:
            raise Problem('unknown_processes', '没有与当前配置匹配的进程记录。')
        if alive(state.get('control')):
            campaigns = API(config).request('/campaigns')
            if any(c['state'] not in ('finished', 'failed') or c.get('backgroundWork') for c in campaigns):
                raise Problem('active_campaigns', '数据目录仍有未结束活动，不能停止后台。', '在工作台处理活动并确认归集完成后重试。')
            for campaign in campaigns:
                detail = API(config).request('/campaigns/'+campaign['id'])
                if detail.get('backgroundWork') or any(o.get('state') == 'running' for o in detail.get('operations', [])):
                    raise Problem('background_work', '后台仍在构建或归集，稍后核对。')
        for role in ('ui', 'control'):
            record = state.get(role)
            if alive(record):
                os.kill(record['pid'], signal.SIGTERM)
        deadline = time.monotonic()+10
        while any(alive(state.get(role)) for role in ('ui', 'control')) and time.monotonic() < deadline:
            time.sleep(.1)
        if any(alive(state.get(role)) for role in ('ui', 'control')):
            raise Problem('stop_pending', '退出请求已发送，进程尚未退出。', '运行 status 核对，不会强制杀死进程。', exit_code=3)
        return {'status': 'passed', 'dataDir': config['data_dir'], 'message': '本地受管进程已退出，活动数据保留。'}
