"""Trusted optional packages; unselected packages are never read or imported."""
import hashlib
import json
import re
from pathlib import Path
from ..store import Refused

IDS = {'model': 'meta-model-reference', 'harness': 'meta-harness-reference'}

def entry_path(plugin):
    package = plugin.get('package')
    if package is None:
        if plugin['id'] in IDS.values(): raise Refused('Optional plugin requires its own package')
        return 'packages/meta-harness/' + plugin['module']
    if package not in IDS.values() or plugin['id'] != package or plugin['module'] != 'index.mjs':
        raise Refused('Untrusted optional Meta package')
    return f'packages/{package}/index.mjs'

def descriptor(source, axis):
    name = IDS[axis]
    root = Path(source) / 'packages' / name
    try:
        document = json.loads((root / 'package.json').read_text())
        meta = document['phyexpMeta']
        if document['name'] != '@phyexp/' + name or meta != {
            'id':name, 'kind':'optional-reference', 'module':'index.mjs',
            'contract':'contracts.json', 'roles':['meta'], 'requires':['metaControl','tools']
        }: raise ValueError('Invalid package declaration')
        for file in ['index.mjs','contracts.json','README.md','package.json']:
            if (root/file).is_symlink() or not (root/file).is_file(): raise ValueError('Missing package asset')
    except (OSError,ValueError,KeyError) as error:
        raise Refused('Optional plugin unavailable: ' + name) from error
    return {'id':name,'package':name,'module':'index.mjs','enabled':True,'config':{},
            'roles':['meta'],'requires':['metaControl','tools']}

def configure(source, composition, policy):
    composition = json.loads(json.dumps(composition))
    if policy is None: return composition
    composition['plugins'] = [p for p in composition['plugins'] if p['id'] not in IDS.values()]
    for axis in IDS:
        if policy.get(axis+'Enabled'): composition['plugins'].append(descriptor(source,axis))
    return composition

def contracts(source, composition, existing):
    result = {}; names = set(existing)
    for plugin in composition['plugins']:
        if not plugin.get('package') or not plugin['enabled']: continue
        entry_path(plugin)
        rel = f"packages/{plugin['package']}/contracts.json"
        content = (Path(source)/rel).read_bytes()
        document = json.loads(content)
        if document.get('version') != 'meta-reference-tools-v1': raise Refused('Unknown optional tool contract')
        for name, spec in document['operations'].items():
            if name in names or spec.get('plugin') != plugin['id'] or not re.fullmatch(r'reference_(model|harness)_(list|submit|status|cancel)',name):
                raise Refused('Conflicting optional tool contract')
            names.add(name)
        result[plugin['id']] = {'path':rel,'version':document['version'],
                               'sha256':hashlib.sha256(content).hexdigest()}
    return result

def frozen_contracts(service, campaign):
    """Read the frozen contract blobs, so uninstall never rewrites old protocols."""
    ref = service.store.get('campaigns',campaign)['config'].get('metaComposition',{})
    bindings = ref.get('optionalToolContracts',{})
    if bindings:
        from ..meta_native_composition import digest
        manifest=json.loads((service.data/'meta-compositions'/ref['id']/'manifest.json').read_text())
        if digest({k:v for k,v in manifest.items() if k!='id'})!=ref['id'] or manifest.get('optionalToolContracts')!=bindings:
            raise Refused('Frozen optional contract manifest mismatch')
    result = {}
    for plugin, binding in bindings.items():
        if plugin not in IDS.values() or not re.fullmatch(r'[0-9a-f]{64}',binding.get('sha256','')):
            raise Refused('Invalid optional contract identity')
        file = service.data/'meta-objects/sha256'/binding['sha256']
        if file.is_symlink() or not file.is_file(): raise Refused('Frozen optional contract unavailable')
        content = file.read_bytes()
        if hashlib.sha256(content).hexdigest() != binding['sha256']: raise Refused('Optional contract integrity mismatch')
        for name,spec in json.loads(content)['operations'].items():
            if name in result or spec.get('plugin') != plugin: raise Refused('Conflicting optional contract')
            result[name] = spec
    return result
