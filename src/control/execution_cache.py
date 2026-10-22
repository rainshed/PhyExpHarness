"""Shared, verified host installations and adapter code; never candidate state.

Cache repair publishes a new generation. Old paths are not overwritten or
removed while another process may still be using them.
"""
import fcntl
import json
import os
import re
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from src.execution.bundle.manifest import canonical, digest, hashes, resolve, checked_path


@contextmanager
def _lock(parent, key):
    parent.mkdir(parents=True, exist_ok=True)
    with (parent / (key + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _current(parent, key):
    pointer = parent / (key + '.json')
    if not pointer.is_file() or pointer.is_symlink():
        return None
    try:
        name = json.loads(pointer.read_text())['generation']
        if not re.fullmatch(key + r'-[0-9a-f]{32}', name):
            return None
        root = parent / name
        return root if root.is_dir() and not root.is_symlink() else None
    except (ValueError, KeyError, OSError):
        return None


def _publish(parent, key, stage):
    destination = parent / (key + '-' + uuid.uuid4().hex)
    stage.rename(destination)
    pointer = parent / (key + '.json')
    temporary = parent / (key + '.json.tmp')
    temporary.write_bytes(canonical({'generation': destination.name}) + b'\n')
    os.replace(temporary, pointer)
    return destination


def _inventory(root):
    modules = root / 'node_modules'
    if not modules.is_dir() or modules.is_symlink():
        raise ValueError('Shared installation is missing')
    result = {}
    for file in sorted(modules.rglob('*')):
        name = file.relative_to(root).as_posix()
        if file.is_symlink():
            if not file.resolve().is_relative_to(modules.resolve()) or not file.exists():
                raise ValueError('Installation link escapes dependency cache')
            result[name] = {'link': os.readlink(file)}
        elif file.is_file():
            result[name] = digest(file.read_bytes())
    if not result:
        raise ValueError('Shared installation is empty')
    return result


def _installation_valid(root, inputs):
    if root is None:
        return False
    try:
        record = json.loads(checked_path(root, 'installation.json').read_text())
        return (record['inputs'] == inputs and
                all(not (root / p).is_symlink() and digest((root / p).read_bytes()) == h
                    for p, h in inputs['files'].items()) and record['files'] == _inventory(root))
    except (OSError, ValueError, KeyError):
        return False


def prepare_dependencies(resolved, cache, log):
    names = ('package.json', 'package-lock.json')
    contents = {p: resolved.asset(p).read_bytes() for p in names}
    # ABI and actual host architecture matter for optional/native dependencies.
    platform = subprocess.check_output(
        ['node', '-p', "JSON.stringify({platform:process.platform,arch:process.arch,abi:process.versions.modules,node:process.version})"],
        text=True, timeout=10).strip()
    inputs = {'schemaVersion': 1, 'platform': json.loads(platform), 'ignoreScripts': True,
              'files': {p: digest(data) for p, data in contents.items()}}
    key = digest(canonical(inputs))
    parent = Path(cache) / 'dependencies'
    with _lock(parent, key):
        existing = _current(parent, key)
        if _installation_valid(existing, inputs):
            log.write('Reused verified dependency installation: ' + key + '\n')
            log.flush()
            return existing
        with tempfile.TemporaryDirectory(prefix='.installing-', dir=parent) as temporary:
            stage = Path(temporary) / 'install'
            stage.mkdir()
            for name, data in contents.items():
                (stage / name).write_bytes(data)
            subprocess.run(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'],
                           cwd=stage, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
            inventory = _inventory(stage)
            (stage / 'installation.json').write_bytes(canonical({'inputs': inputs, 'files': inventory}) + b'\n')
            for file in stage.rglob('*'):
                if file.is_file() and not file.is_symlink():
                    file.chmod(file.stat().st_mode & ~0o222)
            result = _publish(parent, key, stage)
        log.write('Published verified dependency installation: ' + key + '\n')
        log.flush()
        return result


def prepare_runtime(bundle_root, cache, log=None, *, install=True):
    resolved = resolve(bundle_root)
    cache = Path(cache).resolve()
    modules = resolved.root / 'node_modules'
    if (resolved.manifest.get('schemaVersion', 1) == 1 and modules.is_symlink()
            and modules.resolve().is_relative_to(cache / 'dependencies') and install):
        # Historical compatibility views retain their old code and paths. Only
        # their reconstructible installation is shared, and repaired when needed.
        if log is None:
            cache.mkdir(parents=True, exist_ok=True)
            with (cache / 'preparation.log').open('a') as stream:
                return prepare_runtime(bundle_root, cache, stream, install=install)
        dependencies = prepare_dependencies(resolved, cache, log)
        temporary = resolved.root.parent / ('.dependency-link-' + uuid.uuid4().hex)
        temporary.symlink_to(dependencies / 'node_modules', target_is_directory=True)
        os.replace(temporary, modules)
        return resolved.root
    if resolved.manifest.get('schemaVersion') != 2 or (resolved.root / 'objects.json').exists():
        # Legacy and portable projects retain their own declared installation.
        return resolved.root
    cache.mkdir(parents=True, exist_ok=True)
    if log is None:
        with (cache / 'preparation.log').open('a') as stream:
            return prepare_runtime(bundle_root, cache, stream, install=install)
    dependencies = prepare_dependencies(resolved, cache, log) if install else None
    contents = {name: file.read_bytes() for name, file in resolved.assets.items()
                if not name.startswith('plugins/') and name not in ('recipe.json', 'objects.json')}
    # Only image installation consumes this adapter-level header. Candidate
    # resolution always receives the original composition directory explicitly.
    header = canonical({'runnerImage': resolved.manifest['runnerImage']}) + b'\n'
    expected = {p: digest(data) for p, data in contents.items()}
    key = digest(canonical({'files': expected, 'header': digest(header),
                            'dependencies': str(dependencies) if dependencies else None}))
    parent = cache / 'adapters'
    with _lock(parent, key):
        existing = _current(parent, key)
        if existing:
            try:
                valid = (hashes(existing) == expected and
                         checked_path(existing, 'bundle.json').read_bytes() == header and
                         all(checked_path(existing, p) for p in expected) and
                         (not dependencies or ((existing / 'node_modules').is_symlink() and
                          (existing / 'node_modules').resolve() == dependencies / 'node_modules')))
                if valid:
                    return existing
            except (OSError, ValueError):
                pass
        with tempfile.TemporaryDirectory(prefix='.preparing-', dir=parent) as temporary:
            stage = Path(temporary) / 'adapter'
            stage.mkdir()
            for name, data in {**contents, 'bundle.json': header}.items():
                file = stage / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(data)
                file.chmod(0o444)
            if dependencies:
                (stage / 'node_modules').symlink_to(dependencies / 'node_modules', target_is_directory=True)
            return _publish(parent, key, stage)
