"""TensorTrain 2 deployment layout; absent profile preserves upstream behavior."""
import functools
import hashlib
import json
import os
from pathlib import Path


@functools.lru_cache(maxsize=8)
def _load(filename):
    if not filename:
        return None
    value = json.loads(Path(filename).read_text())
    if value.get('version') != 'nfs-primary-v1':
        raise ValueError('Unsupported deployment storage layout')
    for key in ('persistentRoot', 'stateRoot', 'cacheRoot', 'scratchRoot', 'containerRoot'):
        root = Path(value[key])
        if not root.is_absolute() or root.is_symlink() or root.resolve() != root:
            raise ValueError('Storage root must be an absolute physical directory: '+key)
    durable = Path(value['persistentRoot'])
    for key in ('stateRoot', 'cacheRoot', 'scratchRoot'):
        root = Path(value[key])
        if root.is_relative_to(durable) or durable.is_relative_to(root):
            raise ValueError('Persistent and local storage roots must be separate')
    return value


def profile():
    return _load(os.environ.get('PHYEXP_DEPLOYMENT_PROFILE', ''))


def managed(path):
    value = profile()
    return bool(value and Path(path).absolute().is_relative_to(value['persistentRoot']))


def state_path(path):
    path = Path(path)
    if managed(path):
        relative = path.absolute().relative_to(profile()['persistentRoot'])
        if '..' in relative.parts:
            raise ValueError('Escaping state path')
        path = Path(profile()['stateRoot']) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def lock_path(path):
    path = Path(path)
    if managed(path):
        key = hashlib.sha256(str(path.absolute()).encode()).hexdigest()
        path = Path(profile()['stateRoot']) / 'locks' / (key+'.lock')
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def runtime_cache(path):
    return Path(profile()['cacheRoot']) / 'execution' if managed(path) else Path(path)


def task_storage(trial_dir, *, verifier=False):
    """Replace only known data destinations, preserving private/public separation."""
    trial_dir = Path(trial_dir)
    if not managed(trial_dir) or verifier:
        return {}
    root = trial_dir / 'storage'
    paths = {key: root/key for key in ('qsim-private', 'qsim-public')}
    paths['candidate-output'] = trial_dir / 'phyexp' / 'candidate-output'
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    def bind(key, target, readonly=False):
        return {'type':'bind', 'source':str(paths[key]), 'target':target, 'read_only':readonly}
    return {
        'qsim': {'volumes':[bind('qsim-private','/qsim_logs'), bind('qsim-public','/qsim_logs/public_job_results')]},
        'main': {'volumes':[bind('qsim-public','/qsim_logs/public_job_results',True), bind('candidate-output','/tmp/phyexp-output')]},
    }
