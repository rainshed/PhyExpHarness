"""Check source dependency edges; runtime relocation checks cover dynamic resolution."""
import ast
import json
import re
from pathlib import Path

FORBIDDEN = ('src/control/', 'src/evidence/', 'src/reporting/', 'src/exporting/', 'src/meta/', 'src/integrations/', 'src/runtime/', 'packages/')

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
    import sys
    issues=violations(Path(__file__).resolve().parents[1])
    print(json.dumps({'status':'failed' if issues else 'passed','violations':issues},indent=2))
    sys.exit(bool(issues))
