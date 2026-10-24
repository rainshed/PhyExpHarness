"""Content-bound plugin descriptions, independent of executable bundle validation.

Reading verifies the source descriptor and selected source files, never the large
built artifact. Execution/export continue to use manifest.resolve in full.
"""
import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from .manifest import canonical, digest, safe_relative, checked_path, _identity, resolve

VERSION = 'project-plugin-reading-v1'
FIELDS = ('displayName', 'functionSummary', 'purpose', 'mechanism', 'categories')


def plugin_key(plugin):
    identity = [plugin['name'], plugin['version'], plugin.get('digest')]
    # An unavailable/unlocated implementation must not merge across candidates.
    if not plugin.get('digest') and plugin.get('identityScope'):
        identity.append(plugin['identityScope'])
    return 'plugin-' + digest(canonical(identity))


@lru_cache(maxsize=256)
def _bytes(path, signature, expected):
    body = Path(path).read_bytes()
    if expected and digest(body) != expected:
        raise ValueError('Frozen plugin source content mismatch: ' + str(path))
    return body


def read_asset(path, expected=None):
    stat = path.stat()
    signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    # Large source assets are hashed without retaining their bytes in the cache.
    return (_bytes if stat.st_size <= 262_144 else _bytes.__wrapped__)(str(path), signature, expected)


def project_sources(root, expected_id=None):
    """Authenticate the source catalog; returned paths are resolved on demand."""
    root = Path(root).resolve()
    raw = json.loads(read_asset(checked_path(root, 'bundle.json')))
    _identity(raw)
    if expected_id and raw['id'] != expected_id:
        raise ValueError('Candidate bundle identity mismatch')
    if raw.get('schemaVersion') != 3 or raw.get('kind') != 'harness-composition-v3':
        raise ValueError('Expected a complete candidate project')
    reference = raw['sources']
    if not isinstance(reference, str) or not re.fullmatch('[0-9a-f]{64}', reference):
        raise ValueError('Invalid source object reference')
    portable = (root / 'objects.json').exists()
    if portable:
        document = json.loads(read_asset(checked_path(root, 'objects.json'))).get(reference)
        source_root, prefix = root, 'candidate/'
    else:
        object_root = root.parent / reference
        document = json.loads(read_asset(checked_path(object_root, 'object.json')))
        source_root, prefix = object_root / 'assets', ''
    if not isinstance(document, dict) or digest(canonical(document)) != reference:
        raise ValueError('Source object identity mismatch')
    if document.get('schemaVersion') != 1 or document.get('kind') != 'harness-sources':
        raise ValueError('Source object kind mismatch')
    files = document['files']
    for name in files:
        safe_relative(name)
    def asset(name):
        if name not in files:
            raise ValueError('File is not in the frozen source catalog')
        return checked_path(source_root, prefix + name)
    if json.loads(read_asset(asset('harness.json'), files['harness.json'])) != raw['project']:
        raise ValueError('Project declaration mismatch')
    return raw, files, asset


def project_plugins(root, expected_id=None):
    raw, files, asset = project_sources(root, expected_id)
    result = []
    for index, declaration in enumerate(raw.get('plugins', [])):
        p = {**declaration, 'name': declaration.get('name', 'component-' + str(index)),
             'version': declaration.get('version', 'unversioned')}
        p.update(digest=None, manifest={}, entry=None, sourceFiles=[],
                 identityScope=raw['id'] + ':' + str(index), readingVersion=VERSION)
        try:
            path = str(safe_relative(declaration['path'])) if declaration.get('path') else None
            selected = sorted(n for n in files if path and (n == path or n.startswith(path + '/')))
            metadata = {k: declaration[k] for k in FIELDS if k in declaration}
            if path and not selected:
                raise ValueError('Declared plugin path is absent from frozen sources')
            manifest_path = path + '/plugin.json' if path else None
            for name in selected:
                read_asset(asset(name), files[name])
            if manifest_path in selected:
                parsed = json.loads(read_asset(asset(manifest_path), files[manifest_path]))
                if not isinstance(parsed, dict):
                    raise ValueError('Plugin description must be an object')
                if any(k in parsed and parsed[k] != p[k] for k in ('name', 'version')):
                    raise ValueError('Plugin description identity differs from project declaration')
                metadata = {**metadata, **parsed}
            for field in FIELDS[:-1]:
                if field in metadata and not isinstance(metadata[field], str):
                    raise ValueError('Plugin description field must be text: ' + field)
            if 'categories' in metadata and (not isinstance(metadata['categories'], list) or any(not isinstance(c, str) for c in metadata['categories'])):
                raise ValueError('Plugin categories must be an array of strings')
            if selected:
                # Relative files let identical plugins be shared across projects.
                relative = {n: n[len(path) + 1:] if n != path else Path(n).name for n in selected}
                modes = raw.get('buildReceipt', {}).get('inputs', {}).get('sourceModes', {})
                content = {relative[n]: {'sha256': files[n], 'mode': modes.get(n)} for n in selected}
                p.update(digest=digest(canonical(content)), identityScope='plugin-files',
                         sourceFiles=selected, sourcePath=path)
            entry = metadata.get('entry')
            if entry and path:
                entry_path = path + '/' + str(safe_relative(entry))
                if entry_path not in selected:
                    raise ValueError('Declared plugin entry is absent from frozen sources')
                p['entry'] = 'candidate/' + entry_path
            p.update(manifest=metadata, readingStatus='available' if selected else 'unlocated',
                     descriptionSource={'kind': 'frozen-project', 'label': '冻结工程中的插件声明；不代表效果已验证',
                                        'bundleId': raw['id'], 'sources': raw['sources'],
                                        'path': manifest_path if manifest_path in selected else 'harness.json'})
        except (OSError, ValueError, KeyError, TypeError) as error:
            p.update(digest=None, manifest={}, entry=None, sourceFiles=[],
                     identityScope=raw['id'] + ':' + str(index), readingStatus='unavailable',
                     readingError=str(error), descriptionSource={'kind': 'unavailable', 'label': '冻结插件说明不可用：' + str(error)})
        result.append(p)
    return result


def candidate_plugins(candidate):
    original = candidate.get('plugins', [])
    process = candidate.get('executionContract') == 'harbor-process-v1' or (candidate.get('project') or {}).get('runContract') == 'harbor-process-v1'
    process = process or any(p.get('readingVersion') == VERSION or ('path' in p and not p.get('manifest')) for p in original)
    if not process or not original:
        return copy.deepcopy(original)
    try:
        plugins = project_plugins(candidate['bundlePath'], candidate['bundleId'])
    except (OSError, ValueError, KeyError, TypeError) as error:
        plugins = [{**p, 'digest': None, 'manifest': {}, 'entry': None,
                    'identityScope': candidate['bundleId'] + ':' + str(i), 'readingStatus': 'unavailable',
                    'readingError': str(error), 'descriptionSource': {'kind': 'unavailable', 'label': '冻结插件说明不可用：' + str(error)}} for i, p in enumerate(original)]
    # Aliases are resolved only inside this candidate; never index globally by name.
    for i, p in enumerate(plugins):
        if i < len(original) and (original[i]['name'], original[i]['version']) == (p['name'], p['version']):
            p['storedPluginKey'] = original[i].get('storedPluginKey', plugin_key(original[i]))
    return plugins


def candidate_view(candidate):
    return {**candidate, 'plugins': candidate_plugins(candidate)}


def resolve_reference(candidate, key):
    matches = [p for p in candidate_plugins(candidate) if key in (plugin_key(p), p.get('storedPluginKey'))]
    return plugin_key(matches[0]) if len(matches) == 1 else None


def source_view(candidate, key, file=None):
    plugins = candidate_plugins(candidate)
    matches = [p for p in plugins if key in (plugin_key(p), p.get('storedPluginKey'))]
    if len(matches) != 1:
        raise ValueError('Plugin is not an unambiguous member of this execution version')
    plugin = matches[0]
    if plugin.get('readingStatus') == 'unavailable':
        raise ValueError(plugin['readingError'])
    if plugin.get('readingVersion') == VERSION:
        if plugin.get('readingStatus') != 'available':
            raise ValueError(plugin.get('readingError') or 'Plugin source location was not declared')
        _, hashes, asset = project_sources(candidate['bundlePath'], candidate['bundleId'])
        path = plugin['sourcePath']
        names = {n[len(path)+1:] if n != path else Path(n).name: n for n in plugin['sourceFiles']}
        first = asset(next(iter(names.values())))
        directory = first.parent
        if path not in plugin['sourceFiles']:
            for _ in Path(next(iter(names))).parts[:-1]:
                directory = directory.parent
        read = lambda n: read_asset(asset(names[n]), hashes[names[n]])
    else:
        resolved = resolve(candidate['bundlePath'])
        directory = resolved.plugin_roots[plugin['name']]
        prefix = 'plugins/' + plugin['name'] + '/'
        names = {n[len(prefix):]: n for n in resolved.assets if n.startswith(prefix)}
        read = lambda n: resolved.asset(names[n]).read_bytes()
    result = {'candidateId': candidate['id'], 'pluginId': plugin_key(plugin),
              'directory': str(directory), 'files': sorted(names), 'readOnly': True}
    if file is not None:
        if file not in names:
            raise ValueError('File is not in the frozen plugin manifest')
        body = read(file)
        if len(body) > 2_000_000:
            raise ValueError('Source file is too large for preview; open its folder')
        try: content = body.decode()
        except UnicodeDecodeError: content = '二进制资产，请打开文件夹查看。'
        result.update(file=file, content=content)
    return result
