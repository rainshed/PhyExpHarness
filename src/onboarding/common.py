"""Standard-library-only primitives, usable before project dependencies exist."""
import contextlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from src.control.paths import data_dir

ROOT = Path(__file__).resolve().parents[2]


class Problem(Exception):
    def __init__(self, code, message, next_step='', *, exit_code=1):
        super().__init__(message)
        self.code, self.next_step, self.exit_code = code, next_step, exit_code


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default
    except (ValueError, OSError) as error:
        raise Problem('invalid_local_file', f'无法读取 {path}: {error}', '保留原文件，修正内容或权限后重试。') from error


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def locked(path):
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Problem('operation_busy', '同一操作正在另一个进程中执行。', '等待原命令结束后用相同参数查询或重试。', exit_code=3) from None
        yield


def probe(command, *, cwd=ROOT, timeout=15, env=None):
    try:
        return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(command, 127, '', str(error))


def python_path(root=ROOT):
    return Path(root)/'.venv/bin/python'


def settings(args, root=ROOT):
    data = data_dir(getattr(args, 'data_dir', None))
    saved = read_json(data/'onboarding/local.json', {})
    if not isinstance(saved, dict):
        raise Problem('invalid_settings', '本地启动配置必须是 JSON 对象。')
    def choose(name, env, default=None):
        return getattr(args, name, None) or os.environ.get(env) or saved.get(name) or default
    def location(name, env):
        value = choose(name, env)
        return str(Path(value).expanduser().resolve()) if value else None
    control_port = choose('control_port', 'PHYEXP_CONTROL_PORT', 18402)
    ui_port = choose('ui_port', 'PHYEXP_UI_PORT', 18401)
    try:
        control_port, ui_port = int(control_port), int(ui_port)
    except (ValueError, TypeError):
        raise Problem('invalid_port', '端口必须是整数。') from None
    if not all(1 <= port <= 65535 for port in (control_port, ui_port)) or control_port == ui_port:
        raise Problem('invalid_port', '后台/UI 端口须在 1–65535 内且不同。')
    url = os.environ.get('PHYEXP_CONTROL_URL') or f'http://127.0.0.1:{control_port}'
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise Problem('nonlocal_control_url', '本地命令只连接回环 HTTP 后台。', '核对 PHYEXP_CONTROL_URL；远端接入由部署侧负责。')
    if (parsed.port or 80) != control_port:
        raise Problem('control_port_mismatch', 'PHYEXP_CONTROL_URL 与后台端口不一致。', '同时明确 --control-port，或清除冲突的环境变量。')
    return {'source': str(Path(root).resolve()), 'data_dir': str(data),
            'quantum_harbor': location('quantum_harbor', 'PHYEXP_QUANTUM_HARBOR'),
            'model_config': location('model_config', 'PHYEXP_MODEL_CONFIG'),
            'control_port': control_port, 'ui_port': ui_port, 'control_url': url.rstrip('/'),
            'ui_url': f'http://127.0.0.1:{ui_port}'}


def require_platform():
    if sys.platform not in ('darwin', 'linux'):
        raise Problem('unsupported_platform', '本地命令支持 macOS 与 Linux；Windows 请在 Linux 环境中执行。')
