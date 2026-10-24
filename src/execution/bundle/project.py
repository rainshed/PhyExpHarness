"""Freeze complete candidate projects; build code runs only in disposable containers."""
import fcntl
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path
from .manifest import canonical, digest, safe_relative, resolve

VERSION = 'harness-composition-v3'
CONTRACT = 'harbor-process-v1'
IGNORED = {'.git', 'node_modules', '__pycache__', '.venv', '.DS_Store'}


def snapshot(directory):
    root = Path(directory).resolve()
    contents = {}
    for file in sorted(root.rglob('*')):
        relative = file.relative_to(root)
        if any(p in IGNORED for p in relative.parts): continue
        if file.is_symlink() and (not file.exists() or not file.resolve().is_relative_to(root)):
            raise ValueError('Project link escapes its source: ' + str(relative))
        if file.is_file():
            contents[relative.as_posix()] = file.read_bytes()
    if any((root / name).read_bytes() != value for name, value in contents.items()):
        raise ValueError('Project changed while snapshotting')
    if 'harness.json' not in contents: raise ValueError('Missing harness.json')
    spec = json.loads(contents['harness.json'])
    if spec.get('runContract') != CONTRACT: raise ValueError('Unsupported process contract')
    for field in ('entrypoint',):
        argv = spec.get(field)
        if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or '\0' in x for x in argv):
            raise ValueError('Expected argv: ' + field)
        safe_relative(argv[0])
    build = spec['build']
    if not isinstance(build.get('argv'), list) or not build['argv']: raise ValueError('Missing build argv')
    if any(not isinstance(x, str) or '\0' in x for x in build['argv']): raise ValueError('Invalid build argv')
    if not isinstance(build.get('image'), str) or not build['image']: raise ValueError('Missing build image')
    locks = build.get('locks', [])
    if not locks or any(str(safe_relative(p)) not in contents for p in locks):
        raise ValueError('Explicit dependency locks are required')
    # No schema for strategy configuration, plugin capabilities, names or tool roster.
    return contents, spec


def source_tar(contents, prefix=''):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as archive:
        for name, data in sorted(contents.items()):
            info = tarfile.TarInfo(prefix + name); info.size = len(data); info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


def validate_artifact(path, entrypoint, limit):
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        if sum(m.size for m in members) > limit: raise ValueError('Build artifact exceeds declared capacity')
        files = set()
        for item in members:
            name = item.name.removeprefix('./').rstrip('/')
            if not name: continue
            safe_relative(name)
            if not (item.isfile() or item.isdir() or item.issym() or item.islnk()):
                raise ValueError('Artifact contains a non-file object')
            if item.issym() or item.islnk():
                # Resolve without extracting; links may point within the artifact only.
                target = Path('/candidate') / (Path(name).parent if item.issym() else Path()) / item.linkname
                if not target.resolve().is_relative_to('/candidate'): raise ValueError('Artifact link escapes root')
            files.add(name)
        if entrypoint[0] not in files: raise ValueError('Built entrypoint is missing')


def build(contents, spec, cache, log, resources):
    """Content cache holds tar files, never imports generated code into the host."""
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    image = subprocess.check_output(['docker', 'image', 'inspect', spec['build']['image'], '--format', '{{.Id}}'], text=True).strip()
    if not re.fullmatch('sha256:[0-9a-f]{64}', image): raise ValueError('Build image must resolve to an immutable image')
    inputs = {'sources': {k: digest(v) for k, v in contents.items()}, 'image': image,
              'build': spec['build'], 'resources': resources}
    key = digest(canonical(inputs)); record = cache / (key + '.json'); artifact = cache / (key + '.tar')
    with (cache / (key + '.lock')).open('a') as mutex:
        fcntl.flock(mutex, fcntl.LOCK_EX)
        if record.exists() and artifact.exists():
            receipt = json.loads(record.read_text())
            if receipt['artifactSha256'] == digest(artifact.read_bytes()):
                log.write('Reused isolated build ' + key + '\n'); return artifact, receipt
        name = 'phyexp-build-' + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(dir=cache) as temporary:
            stage = Path(temporary)
            (stage / 'source.tar').write_bytes(source_tar(contents, 'candidate/'))
            command = ['docker', 'create', '--name', name, '--cap-drop=ALL', '--security-opt=no-new-privileges',
                       '--user', '0:0', '--cpus', str(resources['cpus']), '--memory', str(resources['memoryBytes']),
                       '--pids-limit', str(resources['pids']), '--workdir', '/candidate', '--entrypoint', spec['build']['argv'][0],
                       image, *spec['build']['argv'][1:]]
            try:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
                # docker cp creates no host mount or control socket inside the build.
                with (stage / 'source.tar').open('rb') as source:
                    subprocess.run(['docker', 'cp', '-', name + ':/'], stdin=source, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
                subprocess.run(['docker', 'start', '--attach', name], stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=resources['timeoutSeconds'])
                code = int(subprocess.check_output(['docker', 'inspect', name, '--format', '{{.State.ExitCode}}'], text=True))
                if code: raise RuntimeError('Candidate build exited ' + str(code))
                with (stage / 'artifact.tar').open('wb') as output:
                    subprocess.run(['docker', 'cp', name + ':/candidate/.', '-'], stdout=output, stderr=log, check=True,
                                   timeout=resources['timeoutSeconds'])
                validate_artifact(stage / 'artifact.tar', spec['entrypoint'], resources['artifactBytes'])
                (stage / 'artifact.tar').replace(artifact)
                receipt = {'inputs': inputs, 'artifactSha256': digest(artifact.read_bytes()), 'status': 'passed', 'checkKind': 'isolated-build-and-entrypoint'}
                record.write_bytes(canonical(receipt) + b'\n')
                return artifact, receipt
            finally:
                subprocess.run(['docker', 'rm', '-f', name], stdout=log, stderr=subprocess.STDOUT, timeout=60)


def freeze_project(source_root, store, directory, recipe, cache, log, resources, *, on_publish=None):
    from .freeze import _object, _publish
    contents, spec = snapshot(directory)
    artifact, receipt = build(contents, spec, cache, log, resources)
    store = Path(store); store.mkdir(parents=True, exist_ok=True)
    source_ref, _ = _object(store, 'harness-sources', contents, on_publish)
    built_ref, _ = _object(store, 'harness-artifact', {'candidate.tar': artifact.read_bytes()}, on_publish)
    delivery = json.loads((Path(source_root) / 'src/execution/process-assets.json').read_text())
    adapter_contents = {name: (Path(source_root) / source).read_bytes() for name, source in delivery.items()}
    adapter_ref, _ = _object(store, 'execution-adapter-v3', adapter_contents, on_publish)
    recipe_bytes = canonical(recipe) + b'\n'
    identity = {'schemaVersion': 3, 'kind': VERSION, 'infrastructureVersion': CONTRACT,
                'sources': source_ref, 'artifact': built_ref, 'adapter': adapter_ref, 'project': spec,
                'buildReceipt': receipt, 'plugins': spec.get('plugins', []),
                'framework': spec.get('framework'), 'profileDigest': digest(canonical(spec.get('profile'))),
                'agentEntry': 'src.execution.adapters.quantum_harbor.process_agent:ProcessHarborAgent',
                'recipeDigest': digest(recipe_bytes)}
    identity['id'] = digest(canonical(identity))
    destination = _publish(store, identity['id'], {'bundle.json': canonical(identity) + b'\n',
        'recipe.json': recipe_bytes}, on_publish, 'bundle')
    resolved = resolve(destination)
    return {'id': identity['id'], 'path': str(destination), 'plugins': identity['plugins'], 'manifest': resolved.manifest}
