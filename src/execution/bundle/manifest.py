"""Resolve immutable compositions and legacy Bundles without executing plugins.

Stored compositions reference sibling content objects. Portable exports carry
the same composition plus object descriptors, with assets at their logical paths.
This module is stdlib-only so the exported verifier needs no builder dependencies.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def source_composition_id(hashes, modes):
    """Source-only identity used by user H0, independent of execution bindings."""
    return digest(canonical({'version': 'user-h0-v1', 'files': {
        name: {'sha256': sha, 'mode': modes.get(name, 0o644)} for name, sha in hashes.items()}}))


def safe_relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Expected a safe relative path')
    path = Path(value)
    if path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('Expected a safe relative path')
    return path


def checked_path(root, relative):
    if root.is_symlink():
        raise ValueError('Bundle path escapes root')
    path = root / safe_relative(relative)
    if any(p.is_symlink() for p in [path, *path.parents] if p != root and root in p.parents):
        raise ValueError('Bundle path escapes root')
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Missing or escaping bundle asset: ' + relative)
    return path


def hashes(root):
    # Preserve the v1 exclusions: installations and Python bytecode are not assets.
    root = Path(root)
    return {str(p.relative_to(root)): digest(p.read_bytes()) for p in sorted(root.rglob('*'))
            if p.is_file() and p.name != '.DS_Store' and p != root / 'bundle.json'
            and '__pycache__' not in p.parts and 'node_modules' not in p.parts and '.venv' not in p.parts}


def _identity(value):
    if digest(canonical({k: v for k, v in value.items() if k != 'id'})) != value.get('id'):
        raise ValueError('Bundle identity mismatch')


def _hashes_match(root, expected):
    actual = hashes(root)
    if actual != expected:
        raise ValueError('Bundle content mismatch: ' + str({
            'added': sorted(set(actual) - set(expected)),
            'missing': sorted(set(expected) - set(actual)),
            'changed': [p for p in actual if p in expected and actual[p] != expected[p]]}))
    for relative in expected:
        checked_path(root, relative)


@dataclass
class ResolvedBundle:
    root: Path
    manifest: dict
    assets: dict
    objects: dict
    plugin_roots: dict

    def asset(self, relative):
        if relative not in self.assets:
            raise ValueError('Asset is not in the frozen manifest: ' + relative)
        return self.assets[relative]


def resolve(root):
    root = Path(root).resolve()
    raw = json.loads(checked_path(root, 'bundle.json').read_text())
    _identity(raw)
    if raw.get('schemaVersion', 1) == 1:
        _hashes_match(root, raw['files'])
        return ResolvedBundle(root, raw, {p: root / p for p in raw['files']}, {},
                              {p['name']: root / 'plugins' / p['name'] for p in raw.get('plugins', [])})
    process = raw.get('schemaVersion') == 3 and raw.get('kind') == 'harness-composition-v3'
    if not process and (raw.get('schemaVersion') != 2 or raw.get('kind') != 'plugin-composition'):
        raise ValueError('Unsupported bundle format')
    portable = (root / 'objects.json').exists()
    catalog = json.loads(checked_path(root, 'objects.json').read_text()) if portable else {}
    objects, assets, files, plugin_roots = {}, {}, {}, {}

    def add_object(reference, kind, prefix=''):
        if not isinstance(reference, str) or not re.fullmatch('[0-9a-f]{64}', reference):
            raise ValueError('Invalid content object reference')
        if portable:
            document = catalog.get(reference)
            object_root = None
        else:
            object_root = root.parent / reference
            if object_root.is_symlink():
                raise ValueError('Content object path escapes store')
            document = json.loads(checked_path(object_root, 'object.json').read_text())
        if not isinstance(document, dict) or digest(canonical(document)) != reference:
            raise ValueError('Content object identity mismatch')
        if document.get('schemaVersion') != 1 or document.get('kind') != kind:
            raise ValueError('Content object kind mismatch')
        objects[reference] = document
        for relative, expected in document['files'].items():
            safe_relative(relative)
            logical = prefix + relative
            if logical in files or logical in ('bundle.json', 'objects.json', 'recipe.json'):
                raise ValueError('Conflicting composition asset: ' + logical)
            file = checked_path(root, logical) if portable else checked_path(object_root / 'assets', relative)
            if digest(file.read_bytes()) != expected:
                raise ValueError('Content object asset mismatch: ' + logical)
            files[logical], assets[logical] = expected, file
        if not portable:
            expected = {'object.json': digest(canonical(document) + b'\n'),
                        **{'assets/' + p: h for p, h in document['files'].items()}}
            _hashes_match(object_root, expected)
        return document

    if process:
        add_object(raw['adapter'], 'execution-adapter-v3')
        add_object(raw['sources'], 'harness-sources', 'candidate/')
        add_object(raw['artifact'], 'harness-artifact')
        recipe_path = checked_path(root, 'recipe.json')
        if digest(recipe_path.read_bytes()) != raw['recipeDigest']:
            raise ValueError('Recipe content mismatch')
        if json.loads(assets['candidate/harness.json'].read_text()) != raw['project']:
            raise ValueError('Project declaration mismatch')
        if digest(assets['candidate.tar'].read_bytes()) != raw['buildReceipt']['artifactSha256']:
            raise ValueError('Built artifact mismatch')
        files['recipe.json'], assets['recipe.json'] = raw['recipeDigest'], recipe_path
        if portable:
            if set(catalog) != set(objects): raise ValueError('Unexpected portable object descriptor')
            files['objects.json'] = digest(canonical(objects) + b'\n')
            assets['objects.json'] = root / 'objects.json'
            _hashes_match(root, files)
        else:
            _hashes_match(root, {'recipe.json': raw['recipeDigest']})
        sources = {name[len('candidate/'):]: sha for name, sha in files.items() if name.startswith('candidate/')}
        modes = raw['buildReceipt'].get('inputs', {}).get('sourceModes', {})
        source_identity = source_composition_id(sources, modes) if set(sources) <= set(modes) else None
        return ResolvedBundle(root, {**raw, 'compositionId': raw['id'], 'sourceCompositionId': source_identity, 'files': files}, assets, objects, {})
    add_object(raw['adapter'], 'execution-adapter')
    add_object(raw['dependencies'], 'dependencies')
    lock = json.loads(assets['package-lock.json'].read_text())
    framework = raw['framework']
    locked = lock['packages'].get('node_modules/' + framework['package'], {})
    if (framework['package'] != '@deepseek-ai/dsh-sdk-minimal' or
            any(framework.get(k) != locked.get(k) for k in ('version', 'resolved', 'integrity')) or
            framework['version'] != raw['dshVersion'] or not framework.get('integrity')):
        raise ValueError('Framework reference does not match dependency lock')
    runner_image = 'phyexp-runner:' + digest(assets['package-lock.json'].read_bytes() +
                                             assets['src/execution/runner/Dockerfile'].read_bytes())[:16]
    if raw['runnerImage'] != runner_image or raw['agentEntry'] != 'src.execution.adapters.quantum_harbor.agent:DeepSeekHarborAgent':
        raise ValueError('Execution entry or image does not match composition')
    plugins = []
    for selection in raw['plugins']:
        name = selection['name']
        if not isinstance(name, str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}', name) or name in plugin_roots:
            raise ValueError('Invalid or repeated plugin name')
        prefix = 'plugins/' + name + '/'
        obj = add_object(selection['object'], 'plugin', prefix)
        metadata = json.loads(assets[prefix + 'plugin.json'].read_text())
        if metadata['name'] != name or metadata['version'] != selection['version']:
            raise ValueError('Plugin reference does not match its implementation')
        if prefix + str(safe_relative(metadata['entry'])) not in assets:
            raise ValueError('Missing plugin entry')
        if any(dependency not in plugin_roots for dependency in metadata['dependencies']):
            raise ValueError('Missing or unordered plugin dependency')
        plugin_roots[name] = assets[prefix + 'plugin.json'].parent
        plugins.append({'name': name, 'version': metadata['version'],
                        'digest': digest(canonical(obj['files'])), 'object': selection['object'],
                        'entry': prefix + str(safe_relative(metadata['entry'])),
                        'config': selection['config'], 'tools': metadata.get('tools', []), 'manifest': metadata})
    recipe_path = checked_path(root, 'recipe.json')
    if digest(recipe_path.read_bytes()) != raw['recipeDigest']:
        raise ValueError('Recipe content mismatch')
    recipe = json.loads(recipe_path.read_text())
    expected_plugins = [{k: p[k] for k in ('name', 'version', 'digest', 'config')} for p in plugins]
    if recipe.get('plugins') != expected_plugins or recipe.get('dshVersion') != raw['dshVersion']:
        raise ValueError('Recipe does not match composition')
    files['recipe.json'], assets['recipe.json'] = raw['recipeDigest'], recipe_path
    if portable:
        if set(catalog) != set(objects):
            raise ValueError('Unexpected or missing portable object descriptor')
        files['objects.json'] = digest(canonical(objects) + b'\n')
        assets['objects.json'] = root / 'objects.json'
        _hashes_match(root, files)
    else:
        _hashes_match(root, {'recipe.json': raw['recipeDigest']})
    manifest = {**raw, 'compositionId': raw['id'], 'files': files, 'plugins': plugins}
    return ResolvedBundle(root, manifest, assets, objects, plugin_roots)


def verify(root):
    return resolve(root).manifest


def asset_path(root, relative):
    return resolve(root).asset(relative)


def read_plugins(root, relative):
    """Read the virtual plugin tree without creating a candidate checkout."""
    bundle = resolve(root)
    base = 'candidate/' if bundle.manifest.get('schemaVersion')==3 else 'plugins/'
    prefix = base if relative in ('', '.') else base + safe_relative(relative).as_posix()
    if prefix in bundle.assets:
        file = bundle.asset(prefix)
        if bundle.manifest.get('schemaVersion')!=3 and file.stat().st_size > 2_000_000:
            raise ValueError('Plugin file too large')
        return {'path': relative, 'content': file.read_text()}
    prefix = prefix.rstrip('/') + '/'
    files = [p[len(base):] for p in bundle.assets if p.startswith(prefix)]
    if not files:
        raise ValueError('Frozen plugin path unavailable')
    return {'path': relative, 'files': files}


def infrastructure_identity(manifest):
    if manifest.get('schemaVersion') == 3:
        return {k: manifest[k] for k in ('adapter', 'infrastructureVersion')}
    if manifest.get('schemaVersion') == 2:
        return {k: manifest[k] for k in ('adapter', 'dependencies', 'framework', 'profileDigest')}
    return {'files': {p: h for p, h in manifest['files'].items()
                      if not p.startswith('plugins/') and p != 'recipe.json'},
            'profileDigest': manifest.get('profileDigest')}


if __name__ == '__main__':
    import sys
    bundle = resolve(sys.argv[1])
    print(json.dumps({'manifest': bundle.manifest,
                      'assets': {p: str(f) for p, f in bundle.assets.items()},
                      'pluginRoots': {p: str(f) for p, f in bundle.plugin_roots.items()},
                      'executionRoot': str(bundle.asset('src/execution/runner/isolated.mjs').parents[1])}))
