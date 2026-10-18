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
        for match in re.finditer(r'''(?:from\s*|import\s*\(|require\s*\(|import\s*)["']([^"']+)["']''',source):
            target=match[1]
            if target.startswith('.'):
                yield str((file.parent/target).resolve().relative_to(root))
            else: yield target

def violations(root):
    root=Path(root).resolve(); graph={}; errors=[]
    for folder in ['src','packages','schemas']:
        for file in (root/folder).rglob('*'):
            if file.suffix not in ['.py','.mjs','.js','.ts','.tsx'] or 'node_modules' in file.parts or 'lib' in file.parts: continue
            key=str(file.relative_to(root))
            try: graph[key]=list(imports(file,root))
            except (ValueError,SyntaxError) as e: errors.append(f'{key}: {e}')
    def resolve(target):
        return next((p for p in [target,target+'.py',target+'.mjs',target+'.js',target+'/index.mjs'] if p in graph),None)
    for origin in graph:
        execution=origin.startswith('src/execution/')
        plugin=origin.startswith(('packages/meta-harness/','packages/meta-workbench/'))
        if not (execution or plugin): continue
        todo=[origin]; seen=set()
        while todo:
            here=todo.pop()
            if here in seen: continue
            seen.add(here)
            for target in graph[here]:
                if (execution and target.startswith(FORBIDDEN)) or (plugin and target.startswith('src/')):
                    errors.append(f'{origin} -> {here} -> {target}: forbidden dependency')
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
