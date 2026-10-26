"""Exact user-selected starting projects. Only the control service reads the catalog."""
import json
import tempfile
import shutil
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError
from .store import Refused
from .plugin_library import ASSEMBLY, HEX
from src.execution.bundle.project import snapshot, SourceFiles
from src.execution.bundle.freeze import _object
from src.execution.bundle.manifest import canonical, digest, checked_path, safe_relative

POLICY = 'user-h0-v1'
TEMPLATE_KIND = 'execution-h0-template-v1'


def defaults(service):
    library=service.plugin_library
    contents,spec=snapshot(service.source/'templates/harness/default')
    with library.locked():
        capture=library.capture(contents,spec,{'kind':'platform-template'})
        if capture['issues']:raise ValueError('Platform plugins are incomplete')
        selected=[]
        declarations={p['path']:p for p in spec['plugins']}
        for plugin in capture['plugins']:
            selected.append({'id':plugin['id'],'config':declarations[plugin['path']].get('config',{})})
        excluded=[p['path'] for p in spec['plugins']]
        base=SourceFiles()
        for name,body in contents.items():
            if any(name==p or name.startswith(p+'/') for p in excluded):continue
            base[name]=body;base.modes[name]=contents.modes[name]
        spec['plugins']=[];spec['runtimeConfig']['plugins']=[]
        base['harness.json']=canonical(spec)+b'\n'
        id,_=_object(library.root,TEMPLATE_KIND,{**base,'template-modes.json':canonical(base.modes)})
        return {'version':POLICY,'templateId':id,'plugins':selected,'templateName':'默认最小运行模板',
                'missing':[p['id'] for p in selected if library.get(p['id'])['deleted']]}


def template(service,id):
    if not isinstance(id,str) or not HEX.fullmatch(id):raise Refused('基础模板不可用')
    root=service.plugin_library.root/id
    descriptor=json.loads(checked_path(root,'object.json').read_bytes())
    if digest(canonical(descriptor))!=id or descriptor.get('kind')!=TEMPLATE_KIND:raise Refused('基础模板身份不匹配')
    files=SourceFiles()
    for name,sha in descriptor['files'].items():
        body=checked_path(root,'assets/'+name).read_bytes()
        if digest(body)!=sha:raise Refused('基础模板内容不匹配')
        files[name]=body
    files.modes=json.loads(files.pop('template-modes.json'))
    return files


def resolve_selection(service,selection=None,*,frozen=False):
    library=service.plugin_library
    if selection is None:
        selection={k:v for k,v in defaults(service).items() if k in ('version','templateId','plugins')}
    if not isinstance(selection,dict) or set(selection)!={'version','templateId','plugins'} or selection['version']!=POLICY:
        raise Refused('需要准确的 H0 模板与插件选择')
    if not isinstance(selection['plugins'],list) or len(selection['plugins'])>100:raise Refused('插件选择应为至多 100 项的列表')
    with library.locked():
        files=template(service,selection['templateId']);spec=json.loads(files['harness.json'])
        rows={};configs={};original_order=[]
        for chosen in selection['plugins']:
            if not isinstance(chosen,dict) or set(chosen)!={'id','config'}:raise Refused('插件选择必须包含准确版本和配置')
            row=library.get(chosen['id'])
            if row['id'] in rows:raise Refused('不能重复选择相同插件版本')
            if row['deleted'] and not frozen:raise Refused('所选插件已从库中删除，请调整选择或明确重新导入：'+row['displayName'])
            available={**row,'deleted':False}
            if library.compatibility(available)['state']!='declared':raise Refused('插件需要适配：'+row['displayName'])
            assembly=row['manifest']['assembly']
            try:Draft202012Validator(assembly.get('configSchema',{})).validate(chosen['config'])
            except ValidationError as error:raise Refused('插件配置不符合规范：'+row['displayName']+'；'+error.message) from error
            if row['name'] in [r['name'] for r in rows.values()]:raise Refused('同一组合不能加载同名插件的多个版本')
            rows[row['id']]=row;configs[row['id']]=chosen['config'];original_order.append(row['id'])
        ordered=[];visiting=set()
        def visit(id):
            if id in ordered:return
            if id in visiting:raise Refused('插件依赖存在循环')
            visiting.add(id)
            assembly=rows[id]['manifest']['assembly']
            for dep in assembly.get('requires',[]):
                if dep not in rows:raise Refused('缺少已确认的插件依赖：'+dep)
                visit(dep)
            if any(x in rows or x in [r['name'] for r in rows.values()] for x in assembly.get('conflicts',[])):
                raise Refused('插件声明了与所选组合的冲突：'+rows[id]['displayName'])
            visiting.remove(id);ordered.append(id)
        for id in original_order:visit(id)
        spec['plugins']=[];spec['runtimeConfig']['plugins']=[]
        locks=[];npm_roots=[]
        for id in ordered:
            row=rows[id];plugin,manifest=library.contents(id);assembly=manifest['assembly']
            prefix='plugins/'+id
            for name,body in plugin.items():
                files[prefix+'/'+name]=body;files.modes[prefix+'/'+name]=plugin.modes[name]
            if 'package.json' in plugin:
                if 'package-lock.json' not in plugin:raise Refused('插件 npm 依赖缺少准确锁：'+row['displayName'])
                lock=json.loads(plugin['package-lock.json'])
                for package in lock.get('packages',{}).values():
                    if package.get('link') or str(package.get('resolved','')).startswith(('file:','/','../')):raise Refused('插件依赖不能引用外部本地文件')
                locks.append(prefix+'/package-lock.json');npm_roots.append(prefix)
            spec['plugins'].append({'name':row['name'],'version':row['version'],'path':prefix,'libraryId':id,'config':configs[id]})
            spec['runtimeConfig']['plugins'].append({'id':row['name'],'name':'./'+prefix+'/'+str(safe_relative(assembly['entry'])),'config':configs[id]})
        if npm_roots:
            # Paths are hashes, commands are fixed argv. Installation stays inside
            # the existing disposable build container, never on the control host.
            script="import {execFileSync} from 'node:child_process';\nfor(const root of "+json.dumps(npm_roots)+")execFileSync('npm',['ci','--no-audit','--no-fund','--prefix',root],{stdio:'inherit'});\n"
            files['build-plugins.mjs']=script.encode();files.modes['build-plugins.mjs']=0o644
            spec['build']['argv']=['/bin/sh','-c',spec['build']['argv'][2].replace(' && node check-assembly.mjs','')+' && node build-plugins.mjs && node check-assembly.mjs']
            spec['build']['locks']+=locks
        files['harness.json']=canonical(spec)+b'\n'
        composition=digest(canonical({'version':POLICY,'files':{n:{'sha256':digest(v),'mode':files.modes.get(n,0o644)} for n,v in files.items()}}))
        normalized={'version':POLICY,'templateId':selection['templateId'],'plugins':[{'id':id,'config':configs[id]} for id in ordered]}
        return {'selection':normalized,'compositionId':composition,'files':files,'project':spec,
                'plugins':[{'id':id,'name':rows[id]['name'],'version':rows[id]['version'],'displayName':rows[id]['displayName']} for id in ordered]}


def materialize(service,selection,destination):
    with service.plugin_library.locked():
        resolved=resolve_selection(service,selection,frozen=True)
        destination=Path(destination)
        if destination.exists():raise Refused('H0 工作目录已存在，不能覆盖')
        destination.parent.mkdir(parents=True,exist_ok=True)
        staging=Path(tempfile.mkdtemp(prefix='.h0-',dir=destination.parent))
        try:
            for name,body in resolved['files'].items():
                target=staging/safe_relative(name);target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(body);target.chmod(resolved['files'].modes.get(name,0o644))
            staging.rename(destination)
        finally:
            if staging.exists():shutil.rmtree(staging)
        return resolved
