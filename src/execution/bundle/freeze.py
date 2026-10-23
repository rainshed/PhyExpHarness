"""Content-addressed assembly. Generated code is copied and checked, never imported on the host."""
import json
import re
import shutil
import tempfile
import errno
from pathlib import Path
from jsonschema import Draft202012Validator


from .manifest import canonical, digest, safe_relative, hashes, verify, checked_path


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


def freeze_legacy(source_root, store, recipe, plugins=(), knowledge=None, *, on_publish=None):
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
        if on_publish:on_publish(staging,'object')
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
        if on_publish:on_publish(destination,'bundle')
        if destination.exists():
            verify(destination)
        else:
            shutil.copytree(staging, destination)
            for file in destination.rglob('*'):
                if file.is_file():
                    file.chmod(0o444)
        return {'id': identity['id'], 'path': str(destination), 'plugins': assembled, 'manifest': identity}


def _publish(store, identity, contents, on_publish=None, kind='object'):
    """Publish a complete immutable directory; concurrent identical writes converge."""
    destination = store / identity
    if destination.is_symlink():
        raise ValueError('Content object path escapes store')
    # Register ownership before writing, including temporary directories that
    # survive a process crash. The callback has no control-layer dependency.
    if on_publish:on_publish(destination,kind)
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix='.publishing-', dir=store) as temp:
            if on_publish:on_publish(Path(temp),'object')
            stage = Path(temp) / 'object'
            stage.mkdir()
            for name, data in contents.items():
                target = stage / safe_relative(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o444)
            try:
                stage.rename(destination)
            except OSError as error:
                if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
    return destination


def _object(store, kind, contents, on_publish=None):
    descriptor = {'schemaVersion': 1, 'kind': kind,
                  'files': {name: digest(data) for name, data in contents.items()}}
    identity = digest(canonical(descriptor))
    _publish(store, identity, {'object.json': canonical(descriptor) + b'\n',
                             **{'assets/' + name: data for name, data in contents.items()}},on_publish)
    return identity, descriptor


def freeze(source_root, store, recipe, plugins=(), knowledge=None, *, legacy=False, on_publish=None):
    if legacy:
        return freeze_legacy(source_root, store, recipe, plugins, knowledge,on_publish=on_publish)
    from src.execution.host.models import provider_route, validate_provider_config, supported_model
    source_root, store = Path(source_root).resolve(), Path(store).resolve()
    recipe = dict(recipe)
    if 'providerConfig' not in recipe:
        recipe['providerConfig'] = provider_route(recipe)
    config = validate_provider_config({'schemaVersion': 1, 'providers': {recipe['provider']: recipe['providerConfig']}})
    if not supported_model(recipe, config):
        raise ValueError('Recipe does not match its frozen model route')
    if recipe['profile'] != 'sdk-minimal' or recipe['dshVersion'] != '0.2.1-rc.2':
        raise ValueError('Unsupported execution profile')
    store.mkdir(parents=True, exist_ok=True)
    delivery = json.loads((source_root / 'src/execution/assets.json').read_text())['delivery']
    adapter_files = {}
    for group in delivery['groups']:
        for name in group['files']:
            if not name.startswith('src/execution/') or name in adapter_files:
                raise ValueError('Invalid or repeated execution delivery asset')
            adapter_files[name] = checked_path(source_root, name).read_bytes()
    for name, source in delivery['entrypoints'].items():
        if name in adapter_files:
            raise ValueError('Conflicting delivery entrypoint')
        adapter_files[name] = checked_path(source_root, source).read_bytes()
    # The allowlist itself travels with the adapter, documenting each included role.
    adapter_files['delivery.json'] = canonical(delivery) + b'\n'
    dependency_files = {name: checked_path(source_root, source).read_bytes()
                        for name, source in delivery['dependencies'].items()}
    lock = json.loads(dependency_files['package-lock.json'])
    for name, package in lock['packages'].items():
        if package.get('link') or str(package.get('resolved', '')).startswith(('file:', '../', '/')):
            raise ValueError('External local dependency forbidden')
        if any(part in name for part in ('meta-harness', 'meta-workbench', 'dsh-web-app', 'dsh-client-ui')):
            raise ValueError('Platform dependency in execution lock')
    installed = {name.removeprefix('node_modules/'): p.get('version')
                 for name, p in lock['packages'].items() if name.startswith('node_modules/')}
    schema = json.loads((source_root / 'schemas/execution/plugin.schema.json').read_text())
    selected, effective_plugins, seen = [], [], set()
    for selection in plugins:
        directory = Path(selection['path']).resolve()
        manifest_bytes = checked_path(directory, 'plugin.json').read_bytes()
        if len(manifest_bytes) > 2_000_000:
            raise ValueError('Plugin manifest exceeds limit')
        manifest = json.loads(manifest_bytes)
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
            if installed.get(package) != version:
                raise ValueError('Package dependency is not available at the declared exact version: ' + package)
        configuration = selection.get('config', {})
        if re.search(r'(/Users/|/home/|[A-Za-z]:\\)', json.dumps(configuration)):
            raise ValueError('Machine-specific configuration cannot be frozen')
        Draft202012Validator.check_schema(manifest['configSchema'])
        Draft202012Validator(manifest['configSchema']).validate(configuration)
        if not manifest['entry'].endswith('.mjs'):
            raise ValueError('Plugin entry must be ESM .mjs')
        tools = manifest.get('tools', [])
        if any(not re.fullmatch('[a-zA-Z][a-zA-Z0-9_]{0,63}', tool) or tool == 'bash' or tool.startswith('mcp__')
               for tool in tools):
            raise ValueError('Plugin cannot redefine fixed tools')
        contents = {'plugin.json': manifest_bytes}
        for name_in_plugin in sorted(set([manifest['entry'], *manifest['assets']])):
            relative = safe_relative(name_in_plugin)
            if relative.name.startswith('.env') or relative.name in ('credentials.json', 'auth.json'):
                raise ValueError('Credential asset forbidden')
            if any(p in ('node_modules', '__pycache__', '.venv', '.DS_Store') for p in relative.parts):
                raise ValueError('Installed dependencies and caches are not plugin assets')
            data = checked_path(directory, name_in_plugin).read_bytes()
            if len(data) > 2_000_000:
                raise ValueError('Plugin asset exceeds limit')
            contents[name_in_plugin] = data
        # A live development workspace may change while it is read. Publish only
        # a consistent snapshot; the next explicit freeze may retry after edits.
        if any(checked_path(directory,name).read_bytes()!=data for name,data in contents.items()):
            raise ValueError('Plugin changed during freeze; retry from a stable workspace')
        reference, descriptor = _object(store, 'plugin', contents, on_publish)
        selected.append({'name': name, 'version': manifest['version'], 'object': reference, 'config': configuration})
        effective_plugins.append({'name': name, 'version': manifest['version'],
                                  'digest': digest(canonical(descriptor['files'])), 'config': configuration})
    adapter, _ = _object(store, 'execution-adapter', adapter_files, on_publish)
    dependencies, _ = _object(store, 'dependencies', dependency_files, on_publish)
    recipe = {k: v for k, v in recipe.items()
              if k not in ('modules', 'id', 'name', 'description', 'notes', 'createdAt', 'updatedAt')}
    recipe['plugins'] = effective_plugins
    recipe_bytes = canonical(recipe) + b'\n'
    framework_package = '@deepseek-ai/dsh-sdk-minimal'
    framework = lock['packages']['node_modules/' + framework_package]
    if framework['version'] != recipe['dshVersion'] or not framework.get('integrity'):
        raise ValueError('Framework lock does not match the selected version')
    identity = {
        'schemaVersion': 2, 'kind': 'plugin-composition', 'infrastructureVersion': 'isolated-v2',
        'dshVersion': recipe['dshVersion'],
        'framework': {'package': framework_package, **{k: framework[k] for k in ('version', 'resolved', 'integrity')}},
        'profileDigest': knowledge['profileDigest'] if knowledge else None,
        'agentEntry': 'src.execution.adapters.quantum_harbor.agent:DeepSeekHarborAgent',
        'runnerImage': 'phyexp-runner:' + digest(dependency_files['package-lock.json'] +
                                               adapter_files['src/execution/runner/Dockerfile'])[:16],
        'adapter': adapter, 'dependencies': dependencies, 'plugins': selected,
        'recipeDigest': digest(recipe_bytes)}
    identity['id'] = digest(canonical(identity))
    Draft202012Validator(json.loads((source_root / 'schemas/execution/composition.schema.json').read_text())).validate(identity)
    destination = _publish(store, identity['id'], {'bundle.json': canonical(identity) + b'\n',
                                                  'recipe.json': recipe_bytes},on_publish,'bundle')
    manifest = verify(destination)
    return {'id': identity['id'], 'path': str(destination), 'plugins': manifest['plugins'],
            'manifest': manifest}
