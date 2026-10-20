"""Content-addressed assembly. Generated code is copied and checked, never imported on the host."""
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from jsonschema import Draft202012Validator


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def safe_relative(value):
    path = Path(value)
    if not isinstance(value, str) or not value or path.is_absolute() or '..' in path.parts or '\\' in value:
        raise ValueError('Expected a safe relative path')
    return path


def copy_tree(source, destination):
    for file in sorted(Path(source).rglob('*')):
        if '__pycache__' in file.parts or file.name == '.DS_Store':
            continue
        if file.is_symlink():
            raise ValueError('Bundle assets may not be symlinks')
        if file.is_file():
            target = destination / file.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)


def hashes(root):
    return {str(p.relative_to(root)): digest(p.read_bytes()) for p in sorted(root.rglob('*'))
            if p.is_file() and p.name != '.DS_Store' and p != root / 'bundle.json' and '__pycache__' not in p.parts
            and 'node_modules' not in p.parts and '.venv' not in p.parts}


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'bundle.json').read_text())
    identity = {k: v for k, v in manifest.items() if k != 'id'}
    if digest(canonical(identity)) != manifest['id']:
        raise ValueError('Bundle identity mismatch')
    actual = hashes(root)
    if actual != manifest['files']:
        raise ValueError('Bundle content mismatch: '+str({'added':sorted(set(actual)-set(manifest['files'])),'missing':sorted(set(manifest['files'])-set(actual)),'changed':[p for p in actual if p in manifest['files'] and actual[p]!=manifest['files'][p]]}))
    for relative in manifest['files']:
        file = root / safe_relative(relative)
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError('Bundle path escapes root')
    return manifest


def freeze(source_root, store, recipe, plugins=(), knowledge=None):
    from src.execution.host.models import provider_route,validate_provider_config,supported_model
    recipe=dict(recipe)
    if 'providerConfig' not in recipe:recipe['providerConfig']=provider_route(recipe)
    model_config=validate_provider_config({'schemaVersion':1,'providers':{recipe['provider']:recipe['providerConfig']}})
    if not supported_model(recipe,model_config):raise ValueError('Recipe does not match its frozen model route')
    source_root, store = Path(source_root).resolve(), Path(store).resolve()
    if recipe['profile'] != 'sdk-minimal' or recipe['dshVersion'] != '0.2.1-rc.2':
        raise ValueError('Unsupported execution profile')
    store.mkdir(parents=True, exist_ok=True)
    schema = json.loads((source_root / 'schemas/execution/plugin.schema.json').read_text())
    assembled = []
    with tempfile.TemporaryDirectory(prefix='.assembling-', dir=store) as temp:
        staging = Path(temp)
        copy_tree(source_root / 'src/execution', staging / 'src/execution')
        copy_tree(source_root / 'templates/standalone', staging)
        # Templates are source-only; dependency installations may not enter a Bundle.
        if (staging / 'node_modules').exists():
            raise ValueError('Installed dependencies are not template assets')
        (staging / 'recipe.json').write_bytes(canonical(recipe) + b'\n')
        fixed_lock=json.loads((staging/'package-lock.json').read_text())
        installed={name.removeprefix('node_modules/'):item.get('version') for name,item in fixed_lock['packages'].items() if name.startswith('node_modules/')}
        seen = set()
        for selection in plugins:
            directory = Path(selection['path']).resolve()
            manifest = json.loads((directory / 'plugin.json').read_text())
            Draft202012Validator(schema).validate(manifest)
            name = manifest['name']
            if not re.fullmatch('[a-z][a-z0-9-]{0,63}', name) or name in seen:
                raise ValueError('Plugin names must be unique safe identifiers')
            if any(dependency not in seen for dependency in manifest['dependencies']):
                raise ValueError('Missing or unordered plugin dependency')
            seen.add(name)
            if set(manifest['capabilities']) - {'tools', 'public-context', 'tool-results', 'model-gateway', 'local-files'}:
                raise ValueError('Plugin capability exceeds execution boundary')
            for package, version in manifest.get('packageDependencies', {}).items():
                if installed.get(package)!=version:
                    raise ValueError('Package dependency is not available at the declared exact version: '+package)
            config = selection.get('config', {})
            if re.search(r'(/Users/|/home/|[A-Za-z]:\\)', json.dumps(config)):
                raise ValueError('Machine-specific configuration cannot be frozen')
            Draft202012Validator.check_schema(manifest['configSchema'])
            Draft202012Validator(manifest['configSchema']).validate(config)
            assets = sorted(set(['plugin.json', manifest['entry'], *manifest['assets']]))
            file_hashes = {}
            target_dir = staging / 'plugins' / name
            for item in assets:
                relative = safe_relative(item)
                source = directory / relative
                if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(directory):
                    raise ValueError('Missing or escaping plugin asset')
                if source.stat().st_size > 2_000_000:
                    raise ValueError('Plugin asset exceeds limit')
                if relative.name.startswith('.env') or relative.name in ['credentials.json', 'auth.json']:
                    raise ValueError('Credential asset forbidden')
                target = target_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                file_hashes[item] = digest(source.read_bytes())
            if not manifest['entry'].endswith('.mjs'):
                raise ValueError('Plugin entry must be ESM .mjs')
            tools = manifest.get('tools', [])
            if any(not re.fullmatch('[a-zA-Z][a-zA-Z0-9_]{0,63}', tool) or tool == 'bash' or tool.startswith('mcp__') for tool in tools):
                raise ValueError('Plugin cannot redefine fixed tools')
            assembled.append({'name': name, 'version': manifest['version'], 'digest': digest(canonical(file_hashes)),
                'entry': f'plugins/{name}/{manifest["entry"]}', 'config': config, 'tools': tools,
                'manifest': manifest})
        effective_recipe={k:v for k,v in recipe.items() if k!='modules'}
        effective_recipe['plugins']=[{k:p[k] for k in ['name','version','digest','config']} for p in assembled]
        (staging/'recipe.json').write_bytes(canonical(effective_recipe)+b'\n')
        lock = json.loads((staging / 'package-lock.json').read_text())
        for name, package in lock['packages'].items():
            if package.get('link') or str(package.get('resolved', '')).startswith(('file:', '../', '/')):
                raise ValueError('External local dependency forbidden')
            if any(part in name for part in ['meta-harness', 'meta-workbench', 'dsh-web-app', 'dsh-client-ui']):
                raise ValueError('Platform dependency in execution lock')
        identity = {'schemaVersion': 1, 'infrastructureVersion': 'isolated-v1', 'dshVersion': recipe['dshVersion'],
            'profileDigest': knowledge['profileDigest'] if knowledge else None,
            'knowledgePackId': knowledge['id'] if knowledge else None,
            'agentEntry': 'src.execution.adapters.quantum_harbor.agent:DeepSeekHarborAgent',
            'runnerImage': 'phyexp-runner:' + digest((staging / 'package-lock.json').read_bytes() + (staging / 'src/execution/runner/Dockerfile').read_bytes())[:16],
            'plugins': assembled, 'files': hashes(staging)}
        identity['id'] = digest(canonical(identity))
        (staging / 'bundle.json').write_bytes(canonical(identity) + b'\n')
        destination = store / identity['id']
        if destination.exists():
            verify(destination)
        else:
            shutil.copytree(staging, destination)
            for file in destination.rglob('*'):
                if file.is_file():
                    file.chmod(0o444)
        return {'id': identity['id'], 'path': str(destination), 'plugins': assembled, 'manifest': identity}
