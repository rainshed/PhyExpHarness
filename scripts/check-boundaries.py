"""Check source dependency edges; runtime relocation checks cover dynamic resolution."""
import ast
import json
import re
from pathlib import Path

FORBIDDEN = ('src/control/', 'src/evidence/', 'src/reporting/', 'src/exporting/', 'src/meta/', 'src/integrations/', 'src/runtime/', 'packages/')

def project_violations(root):
    """Reject concrete deployment implementations in the project distribution.

    This check is for the project branch. Deployment distributions run the
    dependency checks plus their own environment acceptance instead.
    """
    root = Path(root).resolve()
    excluded = {'scripts/check-boundaries.py', 'tests/unit/project_scope_test.py'}
    removed = {
        'scripts/podman-single-uid.py', 'scripts/archive-evidence.py',
        'src/execution/host/container_runtime.py', 'src/control/archive.py',
        'src/evidence/cold.py', 'src/evidence/cold_io.py',
    }
    patterns = {
        'deployment runtime': r'\bpodman\b|\bfakeroot\b|PHYEXP_(?:PODMAN_CONFIG|CONTAINER_RUNTIME)|host[/.]container_runtime',
        'remote archive implementation': r'\bnfs\b|\bColdArchive\b|archive-(?:policy\.json|index\.sqlite)|src[/.]evidence[/.]cold(?:\b|_)',
        'host deployment': r'tensor[ _-]?train[ _-]?2|\btailscale\b|/var/tmp/phyexp-[\w-]+',
    }
    errors = [f'{name}: deployment-only file' for name in sorted(removed) if (root/name).exists()]
    files = [root/'AGENTS.md', root/'README.md', root/'package.json']
    for folder in ('src', 'packages', 'scripts', 'tests', 'schemas', 'profiles', 'recipes',
                   'experiments', 'templates', 'docs', 'knowledge'):
        files.extend((root/folder).rglob('*'))
    for file in files:
        if not file.is_file() or file.is_symlink(): continue
        relative = file.relative_to(root)
        if relative.as_posix() in excluded: continue
        if any(part in ('node_modules', '__pycache__', 'lib') for part in relative.parts): continue
        if relative.as_posix().startswith('knowledge/plugin-sdk/reference/'): continue
        if file.suffix not in ('.py', '.mjs', '.js', '.ts', '.tsx', '.json', '.yml', '.yaml', '.md', '.sh'): continue
        source = file.read_text()
        for label, pattern in patterns.items():
            if re.search(pattern, source, re.I): errors.append(f'{relative}: {label} belongs outside the project distribution')
    return sorted(set(errors))

def imports(file, root):
    source=file.read_text()
    if file.suffix=='.py':
        tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                for alias in node.names: yield alias.name.replace('.', '/')
            elif isinstance(node,ast.ImportFrom):
                if node.level:
                    parent=file.parent
                    for _ in range(node.level-1): parent=parent.parent
                    yield str((parent/(node.module or '').replace('.', '/')).resolve().relative_to(root))
                else: yield (node.module or '').replace('.', '/')
    else:
        for match in re.finditer(r'''(?:from\s*|import\s*\(|require\s*\(|import\s*|@import\s*(?:url\(\s*)?)["']([^"']+)["']''',source):
            target=match[1]
            if target.startswith('.'):
                yield str((file.parent/target).resolve().relative_to(root))
            else: yield target

def violations(root):
    root=Path(root).resolve(); graph={}; errors=[]
    for folder in ['src','packages','schemas']:
        for file in (root/folder).rglob('*'):
            if file.suffix not in ['.py','.mjs','.js','.ts','.tsx','.css'] or 'node_modules' in file.parts or 'lib' in file.parts: continue
            key=str(file.relative_to(root))
            try: graph[key]=list(imports(file,root))
            except (ValueError,SyntaxError) as e: errors.append(f'{key}: {e}')
    packages={}
    for manifest in (root/'packages').glob('*/package.json'):
        data=json.loads(manifest.read_text()); folder=str(manifest.parent.relative_to(root))
        kind=data.get('phyexpWorkbench',{}).get('kind')
        packages[data['name']]={'folder':folder,'kind':kind,'data':data}
    def owner(target):
        return next((v for v in packages.values() if target.startswith(v['folder']+'/')),None)
    def package_target(target):
        for name,package in packages.items():
            if target==name or target.startswith(name+'/'):
                sub='.' if target==name else './'+target[len(name)+1:]
                entry=package['data'].get('exports',{}).get(sub)
                if isinstance(entry,str): return package['folder']+'/'+entry.removeprefix('./'),True
                return package['folder']+'/'+target[len(name):].lstrip('/'),False
        return target,True
    def resolve(target):
        return next((p for p in [target,*[target+ext for ext in ['.py','.mjs','.js','.ts','.tsx','.css']],*[target+'/index'+ext for ext in ['.mjs','.js','.ts','.tsx']]] if p in graph),None)
    for package in packages.values():
        # Dependency declarations are edges even when a bundler tree-shakes them.
        deps={**package['data'].get('dependencies',{}),**package['data'].get('peerDependencies',{}),**package['data'].get('devDependencies',{})}
        graph[package['folder']+'/package.json']=list(deps)
    for origin in graph:
        execution=origin.startswith('src/execution/')
        source_package=owner(origin)
        plugin=origin.startswith(('packages/meta-harness/','packages/meta-workbench')) or bool(source_package and source_package['kind'])
        if not (execution or plugin): continue
        if source_package and source_package['kind']=='client' and not origin.endswith('package.json'):
            source=(root/origin).read_text()
            if origin.endswith(('.tsx','.css')) or re.search(r'\b(?:document|window|HTMLElement)\b',source):
                errors.append(f'{origin}: public client contains presentation code')
        todo=[origin]; seen=set()
        while todo:
            here=todo.pop()
            if here in seen: continue
            seen.add(here)
            for imported in graph[here]:
                target,exported=package_target(imported); target_package=owner(target)
                if (execution and target.startswith(FORBIDDEN)) or (plugin and target.startswith('src/')):
                    errors.append(f'{origin} -> {here} -> {target}: forbidden dependency')
                if source_package and target_package and source_package!=target_package:
                    if target_package['kind']=='ui':
                        errors.append(f'{origin} -> {here} -> {target}: concrete UI dependency')
                    if owner(here)==source_package and (not exported or imported.startswith('packages/')):
                        errors.append(f'{origin} -> {target}: use the public package exports')
                if imported.startswith('@phyexp/') and target==imported:
                    errors.append(f'{origin} -> {imported}: unknown workspace package')
                dest=resolve(target)
                if dest: todo.append(dest)
    for folder in ['src/execution', 'schemas/execution', 'recipes']:
        for file in (root/folder).rglob('*'):
            if file.suffix not in ['.json', '.yml', '.yaml']: continue
            # Configuration and dynamic entry points are dependency edges too.
            for forbidden in FORBIDDEN:
                if forbidden in file.read_text(): errors.append(f'{file.relative_to(root)}: forbidden configuration reference {forbidden}')
    manifest=root/'src/execution/assets.json'
    if manifest.exists():
        data=json.loads(manifest.read_text())
        for entry in data['dynamicAssets']:
            target=root/entry
            if not entry.startswith('src/execution/') or not target.is_file() or target.is_symlink():
                errors.append(f'{entry}: invalid declared dynamic execution asset')
    return sorted(set(errors))

if __name__=='__main__':
    import argparse,sys
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', action='store_true', help='Also enforce project-only source and documentation scope')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    issues=violations(root)
    if args.project: issues+=project_violations(root)
    print(json.dumps({'status':'failed' if issues else 'passed','violations':issues},indent=2))
    sys.exit(bool(issues))
