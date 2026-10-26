"""Pinned project setup and read-only prerequisite checks."""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from .common import ROOT, Problem, locked, probe, python_path, read_json, write_json

DEFAULT_TASK = 'time_budgeted_hamlearn_10q'


def runtime_checks(root=ROOT):
    rows = []
    def add(id, ok, detail, next_step):
        rows.append({'id': id, 'status': 'passed' if ok else 'failed', 'detail': detail, 'nextStep': '' if ok else next_step})
    add('platform', sys.platform in ('darwin', 'linux'), f'{sys.platform}/{platform.machine()}', '使用 macOS 或 Linux；平台验收范围见安装指南。')
    add('python', sys.version_info[:2] == (3, 13), platform.python_version(), '使用 Python 3.13 运行本命令。')
    node = probe(['node', '--version'], cwd=root)
    match = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', node.stdout.strip())
    add('node', bool(match and int(match[1]) == 24 and int(match[2]) >= 13), node.stdout.strip() or 'Node 不可用', '安装 Node.js 24.13+（24.x），重新打开终端。')
    npm = probe(['npm', '--version'], cwd=root)
    add('npm', npm.returncode == 0, npm.stdout.strip() or 'npm 不可用', '使用随 Node.js 安装的 npm。')
    git = probe(['git', '--version'], cwd=root)
    add('git', git.returncode == 0, git.stdout.strip() or 'Git 不可用', '安装 Git。')
    return rows


def lock_fingerprint(root=ROOT):
    names = ['package.json', 'package-lock.json', 'requirements-control.lock', 'scripts/build-knowledge.py', 'scripts/build-workbench.mjs']
    names += [str(p.relative_to(root)) for p in sorted((root/'packages').glob('*/package.json'))]
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode()); digest.update((root/name).read_bytes())
    return digest.hexdigest()


def installed(root=ROOT):
    python = python_path(root)
    if not python.is_file():
        return False, '项目虚拟环境不存在'
    script = '''import importlib.metadata as m, json, re, sys
from pathlib import Path
expected=dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\\s]+)",Path(sys.argv[1]).read_text(),re.M))
bad=[]
for name,version in expected.items():
 try: actual=m.version(name)
 except m.PackageNotFoundError: actual=None
 if actual!=version: bad.append(name)
print(json.dumps({"python":list(sys.version_info[:2]),"mismatches":bad}))
'''
    result = probe([str(python), '-c', script, str(root/'requirements-control.lock')], cwd=root, timeout=30)
    try:
        data = json.loads(result.stdout)
        if data['python'] != [3, 13] or data['mismatches']:
            return False, 'Python 环境或锁版本不匹配：'+', '.join(data['mismatches'])
    except (ValueError, KeyError):
        return False, '项目 Python 不可用'
    if not (root/'node_modules/.bin/dsh').is_file() or not (root/'node_modules/esbuild/package.json').is_file():
        return False, 'npm 依赖不完整'
    receipt = read_json(root/'.runtime/setup.json', {})
    if receipt.get('fingerprint') != lock_fingerprint(root):
        return False, '安装回执与当前依赖清单不一致'
    return True, '完整 Python 锁与安装回执匹配'


def setup(root=ROOT, *, repair=False):
    checks = runtime_checks(root)
    if any(row['status'] == 'failed' for row in checks):
        return {'status': 'failed', 'checks': checks}
    with locked(root/'.runtime/setup.lock'):
        ready, _ = installed(root)
        log_path = root/'.runtime/setup.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'w') as log:
            env = dict(os.environ)
            env['PATH'] = str(python_path(root).parent)+os.pathsep+env.get('PATH', '')
            def run(command):
                log.write(json.dumps(command)+'\n'); log.flush()
                print('执行：'+' '.join(command), file=sys.stderr, flush=True)
                try:
                    result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
                except OSError as error:
                    raise Problem('setup_command_failed', f'无法执行安装命令：{command[0]}', f'查看 {log_path}') from error
                if result.returncode:
                    raise Problem('setup_command_failed', f'安装步骤失败（退出 {result.returncode}）：{command[0]}', f'查看 {log_path}，修复后重跑 setup。')
            python = python_path(root)
            if not python.exists():
                if python.parent.parent.exists():
                    raise Problem('invalid_venv', '.venv 已存在但不是有效虚拟环境。', '核对现有目录后手动修复；安装器不会删除它。')
                run([sys.executable, '-m', 'venv', str(root/'.venv')])
            version = probe([str(python), '-c', 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")'], cwd=root)
            if version.stdout.strip() != '3.13':
                raise Problem('wrong_venv_python', '已有 .venv 不是 Python 3.13。', '保留必要文件后自行换成 Python 3.13 虚拟环境。')
            if repair or not ready:
                run([str(python), '-m', 'pip', 'install', '--require-hashes', '-r', 'requirements-control.lock'])
                run(['npm', 'ci'])
            run([str(python), '-m', 'pip', 'check'])
            run(['npm', 'run', 'build'])
        write_json(root/'.runtime/setup.json', {'fingerprint': lock_fingerprint(root), 'python': str(python)})
        return {'status': 'passed', 'reusedDependencies': ready and not repair, 'log': str(log_path), 'nextStep': '运行 doctor --quantum-harbor /absolute/Quantum-Harbor。'}


def doctor(config, *, task=DEFAULT_TASK, project_only=False, root=ROOT):
    checks = runtime_checks(root)
    def add(id, ok, detail, next_step='', warning=False):
        checks.append({'id': id, 'status': 'passed' if ok else 'warning' if warning else 'failed', 'detail': detail, 'nextStep': '' if ok else next_step})
    ready, detail = installed(root)
    add('dependencies', ready, detail, '运行 setup；已安装但损坏时使用 setup --repair。')
    built = (root/'knowledge/plugin-sdk/reference/manifest.json').is_file() and (root/'packages/meta-workbench-studio/lib/client.js').is_file()
    add('build', built, 'SDK 资料和 Studio 产物'+('存在' if built else '不完整'), '运行 setup 或 npm run build。')
    target = Path(config['data_dir'])
    while not target.exists():
        target = target.parent
    add('data_directory', target.is_dir() and os.access(target, os.W_OK | os.X_OK), config['data_dir'], '选择当前用户可写的本地数据目录。')
    if project_only:
        return {'status': 'failed' if any(r['status'] == 'failed' for r in checks) else 'passed', 'scope': 'project-only', 'checks': checks, 'modelRequests': 0}
    engine = probe(['docker', 'info', '--format', '{{.OSType}}/{{.Architecture}}'], cwd=root)
    docker_ready = engine.returncode == 0 and engine.stdout.strip().startswith('linux/')
    add('docker', docker_ready, engine.stdout.strip() or 'Docker 引擎不可连接', '启动支持 Linux 容器的 Docker 并核对当前 context/权限。')
    compose = probe(['docker', 'compose', 'version'], cwd=root)
    add('docker_compose', compose.returncode == 0, compose.stdout.strip() or 'Docker Compose 不可用', '安装 Docker Compose v2 插件。')
    quantum = Path(config['quantum_harbor']) if config.get('quantum_harbor') else None
    if not re.fullmatch('[a-zA-Z0-9_-]+', task):
        raise Problem('invalid_task', '任务名称只能包含字母、数字、下划线和连字符。')
    files = ['pyproject.toml', 'docker/agent/Dockerfile', 'docker/qsim/Dockerfile', 'tools/build_qsim_images.py', f'harbor_tasks/{task}/task.toml']
    valid = bool(quantum and all((quantum/name).is_file() for name in files))
    add('quantum_harbor', valid, str(quantum) if quantum else '未设置 Quantum-Harbor 路径', '按安装指南获取 Quantum-Harbor，传入 --quantum-harbor。')
    if valid:
        revision = probe(['git', 'rev-parse', 'HEAD'], cwd=quantum)
        dirty = probe(['git', 'status', '--porcelain'], cwd=quantum)
        add('quantum_revision', revision.returncode == 0 and not dirty.stdout.strip(), revision.stdout.strip() or '无 Git 版本', '使用明确版本的干净 checkout；已有活动保留原任务来源。', warning=True)
        try:
            spec = tomllib.loads((quantum/f'harbor_tasks/{task}/task.toml').read_text())
            images = ['qiqcbench-agent:latest', spec['verifier']['environment']['docker_image']]
            for reference in images:
                result = probe(['docker', 'image', 'inspect', reference, '--format', '{{.Id}}']) if docker_ready else None
                add('image:'+reference, bool(result and result.returncode == 0), reference, '按安装指南构建 agent 和所选任务 verifier；活动创建时准备冻结 main/qsim。')
        except (OSError, ValueError, KeyError, TypeError):
            add('task_config', False, '任务 TOML 缺少独立 verifier 镜像', '核对兼容的 Quantum-Harbor 版本。')
    return {'status': 'failed' if any(r['status'] == 'failed' for r in checks) else 'passed', 'scope': 'experiment-prerequisites', 'checks': checks, 'modelRequests': 0}
