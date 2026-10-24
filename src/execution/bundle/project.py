"""Freeze complete candidate projects; build code runs only in disposable containers."""
import fcntl
import io
import json
import os
import re
import shutil
import select
import time
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path
from .manifest import canonical, digest, safe_relative, resolve

VERSION = 'harness-composition-v3'
CONTRACT = 'harbor-process-v1'
IGNORED = {'.git', 'node_modules', '__pycache__', '.venv', '.DS_Store'}


class SourceFiles(dict):
    """Source bytes and executable modes are one frozen build input."""
    def __init__(self):super().__init__();self.modes={}


def snapshot(directory):
    root = Path(directory).resolve();contents = SourceFiles()
    def visit(directory, ancestors):
        resolved=directory.resolve()
        if not resolved.is_relative_to(root): raise ValueError('Project link escapes its source: '+str(directory.relative_to(root)))
        if resolved in ancestors:raise ValueError('Project directory link cycle: '+str(directory.relative_to(root)))
        for file in sorted(directory.iterdir()):
            if file.name in IGNORED:continue
            relative=file.relative_to(root).as_posix()
            if file.is_symlink() and (not file.exists() or not file.resolve().is_relative_to(root)):
                raise ValueError('Project link escapes its source: '+relative)
            if file.is_dir():visit(file,ancestors|{resolved})
            elif file.is_file():
                contents[relative]=file.read_bytes();contents.modes[relative]=0o755 if file.stat().st_mode&0o111 else 0o644
            else:raise ValueError('Unsupported source filesystem object: '+relative)
    visit(root,set())
    if any((root / name).read_bytes() != value or (0o755 if (root/name).stat().st_mode&0o111 else 0o644)!=contents.modes[name] for name,value in contents.items()):
        raise ValueError('Project changed while snapshotting')
    if 'harness.json' not in contents: raise ValueError('Missing harness.json')
    spec = json.loads(contents['harness.json'])
    from jsonschema import Draft202012Validator
    schema=Path(__file__).resolve().parents[3]/'schemas/execution/harness-project.schema.json'
    Draft202012Validator(json.loads(schema.read_text())).validate(spec)
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
    if not isinstance(locks,list) or any(str(safe_relative(p)) not in contents for p in locks):
        raise ValueError('Explicit dependency locks are required')
    # No schema for strategy configuration, plugin capabilities, names or tool roster.
    return contents, spec


def source_tar(contents, prefix=''):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as archive:
        for name, data in sorted(contents.items()):
            info = tarfile.TarInfo(prefix + name); info.size = len(data); info.mode = getattr(contents,'modes',{}).get(name,0o644)
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
              'build': spec['build'], 'resources': resources, 'sourceModes':getattr(contents,'modes',{})}
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
                # Bound bytes while receiving, before any oversized artifact can
                # consume the host disk. A stalled engine also has a local timeout.
                with (stage/'artifact.tar').open('wb') as output:
                    copied=subprocess.Popen(['docker','cp',name+':/candidate/.','-'],stdout=subprocess.PIPE,stderr=log)
                    received=0;expires=time.monotonic()+resources['timeoutSeconds']
                    try:
                        while True:
                            remaining=expires-time.monotonic()
                            if remaining<=0:raise TimeoutError('Build artifact transfer timed out')
                            ready,_,_=select.select([copied.stdout],[],[],remaining)
                            if not ready:raise TimeoutError('Build artifact transfer timed out')
                            chunk=os.read(copied.stdout.fileno(),65536)
                            if not chunk:break
                            received+=len(chunk)
                            if received>resources['artifactBytes']:raise ValueError('Build artifact exceeds declared capacity')
                            output.write(chunk)
                        if copied.wait(timeout=max(.001,expires-time.monotonic())):raise RuntimeError('Build artifact transfer failed')
                    finally:
                        if copied.poll() is None:copied.kill();copied.wait()
                        copied.stdout.close()
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
                'buildReceipt': receipt, 'plugins': [{'name':p.get('name','component-'+str(i)), 'version':p.get('version','unversioned'), **p} for i,p in enumerate(spec.get('plugins', []))],
                'framework': spec.get('framework'), 'profileDigest': digest(canonical(spec.get('profile'))),
                'agentEntry': 'src.execution.adapters.quantum_harbor.process_agent:ProcessHarborAgent',
                'recipeDigest': digest(recipe_bytes)}
    identity['id'] = digest(canonical(identity))
    destination = _publish(store, identity['id'], {'bundle.json': canonical(identity) + b'\n',
        'recipe.json': recipe_bytes}, on_publish, 'bundle')
    resolved = resolve(destination)
    return {'id': identity['id'], 'path': str(destination), 'plugins': identity['plugins'], 'manifest': resolved.manifest}
