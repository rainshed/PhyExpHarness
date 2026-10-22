"""v2 Meta compositions: exact content refs, shared blobs and rebuildable runtime cache."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import fcntl
import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .store import Refused,encoded
from src.execution.bundle.manifest import safe_relative

VERSION='meta-composition-v2'
def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
def file_hash(file):return hashlib.sha256(file.read_bytes()).hexdigest()
def source_group(source,roots):
    files={};pending=list(roots)
    while pending:
        rel=pending.pop();file=source/rel
        if rel in files:continue
        if file.is_symlink() or not file.is_file():raise Refused('Meta source unavailable: '+rel)
        files[rel]=file_hash(file)
        if file.suffix=='.mjs':
            for dep in re.findall(r"['\"](\.{1,2}/[^'\"]+\.(?:mjs|json|yml))['\"]",file.read_text()):
                target=(file.parent/dep).resolve()
                if not target.is_relative_to(source):raise Refused('Meta import escapes source')
                pending.append(target.relative_to(source).as_posix())
    return files

def validate(manifest,source):
    if manifest.get('version')!=VERSION or not isinstance(manifest.get('plugins'),list):raise Refused('Unknown native Meta composition')
    ids=set();enabled=[]
    for p in manifest['plugins']:
        if p.get('id') in ids or not isinstance(p.get('id'),str):raise Refused('Duplicate/invalid Meta plugin')
        ids.add(p['id']);module=p.get('module','');roles=p.get('roles')
        if not re.fullmatch(r'[-\w]+\.mjs',module) or not (source/'packages/meta-harness'/module).is_file():raise Refused('Invalid Meta module')
        if not isinstance(roles,list) or not roles or set(roles)-{'meta','research','reviewer'}:raise Refused('Invalid Meta roles')
        if type(p.get('enabled')) is not bool or not isinstance(p.get('config'),dict):raise Refused('Meta enabled/config required')
        if p['enabled']:enabled.append(p)
    for role in ['meta','research','reviewer']:
        scoped=[p for p in enabled if role in p['roles']]
        if not any('metaControl' in p.get('provides',[]) for p in scoped):raise Refused('Missing scoped metaControl')
        for p in scoped:
            for need in p.get('requires',[]):
                if need not in ['tools','systemPrompt','subagents'] and not any(q['id']==need or need in q.get('provides',[]) for q in scoped):raise Refused('Missing dependency '+need)
    if manifest.get('mode')=='complete':
        for id in ['meta-control','meta-campaign','meta-experiments','meta-evidence','meta-reporting']:
            if not any(p['id']==id and 'meta' in p['roles'] for p in enabled):raise Refused('Missing complete Meta capability '+id)
    return manifest

def prepare_image(source,data):
    inputs={p:file_hash(source/p) for p in ['packages/meta-harness/runtime-package.json','packages/meta-harness/runtime-package-lock.json','packages/meta-harness/Dockerfile','packages/meta-harness/development-dependencies.json']}
    arch=subprocess.run(['docker','info','--format','{{.Architecture}}'],text=True,capture_output=True,check=True,timeout=30).stdout.strip()
    arch={'aarch64':'arm64','x86_64':'amd64'}.get(arch,arch)
    key=digest({'inputs':inputs,'architecture':arch});tag='phyexp-meta:'+key;directory=data/'cache/meta-images';directory.mkdir(parents=True,exist_ok=True)
    with (directory/(key+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        def inspect():return subprocess.run(['docker','image','inspect',tag,'--format','{{.Id}}'],text=True,capture_output=True,timeout=30)
        image=inspect()
        if image.returncode:
            with tempfile.TemporaryDirectory(dir=directory) as temp,(directory/(key+'.log')).open('w') as log:
                for name in ['package.json','package-lock.json']:shutil.copyfile(source/('packages/meta-harness/runtime-'+name),Path(temp)/name)
                shutil.copyfile(source/'packages/meta-harness/Dockerfile',Path(temp)/'Dockerfile')
                packages=json.loads((source/'packages/meta-harness/development-dependencies.json').read_text())['architectures'].get(arch)
                if not packages:raise Refused('Unsupported Meta development architecture: '+arch)
                cache=data/'cache/meta-dependencies';cache.mkdir(parents=True,exist_ok=True)
                stage=Path(temp)/'development';stage.mkdir()
                def download(row):
                    if not re.fullmatch(r'[0-9a-f]{64}',row['sha256']) or not row['url'].startswith('https://deb.debian.org/debian/pool/'):raise Refused('Invalid development dependency reference')
                    if Path(row['file']).name!=row['file']:raise Refused('Invalid dependency filename')
                    target=cache/row['sha256']
                    if not target.exists():
                        pending=stage/(row['file']+'.download')
                        subprocess.run(['curl','--fail','--silent','--show-error','--location','--retry','2','--max-time','120','--output',str(pending),row['url']],stdout=log,stderr=log,check=True,timeout=360)
                        if file_hash(pending)!=row['sha256']:raise Refused('Development dependency integrity mismatch')
                        os.replace(pending,target)
                    if target.is_symlink() or file_hash(target)!=row['sha256']:raise Refused('Development dependency cache corrupted')
                    shutil.copyfile(target,stage/row['file'])
                with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(download,packages))
                npm_cache=data/'cache/meta-npm';npm_cache.mkdir(parents=True,exist_ok=True)
                npm_stage=Path(temp)/'npm-packages';npm_stage.mkdir()
                locked=json.loads((source/'packages/meta-harness/runtime-package-lock.json').read_text())['packages']
                cpu='arm64' if arch=='arm64' else 'x64'
                archives={p['integrity']:p for p in locked.values() if p.get('integrity') and p.get('resolved','').startswith('https://registry.npmjs.org/')
                    and ('os' not in p or 'linux' in p['os']) and ('cpu' not in p or cpu in p['cpu'])
                    # Office rendering is not loaded by this headless research profile.
                    # Leave its optional platform payload absent; never omit required
                    # terminal, image-reading or filesystem-search native binaries.
                    and not (p.get('optional') and '/libreoffice-kit-' in p.get('resolved',''))}
                def npm_download(item):
                    integrity,row=item;algorithm,expected=integrity.split('-',1)
                    if algorithm not in ['sha512','sha256','sha1']:raise Refused('Unsupported npm integrity algorithm')
                    name=hashlib.sha256(integrity.encode()).hexdigest()+'.tgz';target=npm_cache/name
                    if not target.exists():
                        pending=npm_stage/(name+'.download')
                        subprocess.run(['curl','--fail','--silent','--show-error','--location','--retry','2','--max-time','120','--output',str(pending),row['resolved']],stdout=log,stderr=log,check=True,timeout=360)
                        actual=base64.b64encode(hashlib.new(algorithm,pending.read_bytes()).digest()).decode()
                        if actual!=expected:raise Refused('npm dependency integrity mismatch')
                        os.replace(pending,target)
                    actual=base64.b64encode(hashlib.new(algorithm,target.read_bytes()).digest()).decode()
                    if target.is_symlink() or actual!=expected:raise Refused('npm dependency cache corrupted')
                    shutil.copyfile(target,npm_stage/name)
                with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(npm_download,archives.items()))
                subprocess.run(['docker','build','-t',tag,temp],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
            image=inspect()
        if image.returncode or not re.fullmatch(r'sha256:[0-9a-f]{64}',image.stdout.strip()):raise Refused('Native Meta image unavailable')
        return image.stdout.strip()

def freeze(source,data,config):
    from .meta_context import system_prompt
    source=Path(source).resolve();data=Path(data);plugin=source/'packages/meta-harness'
    composition=validate(config.get('metaCompositionConfig') or json.loads((plugin/'composition-native.json').read_text()),source)
    groups={p['id']:source_group(source,['packages/meta-harness/'+p['module']]) for p in composition['plugins']}
    support=['src/control/meta_worker_native.mjs','src/control/meta_gateway.mjs','src/control/meta_host.mjs','src/control/meta_outputs.mjs',
        'src/execution/runner/isolated.mjs','src/execution/runner/boot.mjs','src/execution/runner/gateway_plugin.mjs','src/execution/runner/assets/sdk-minimal.yml',
        'packages/meta-harness/composition-native.mjs','packages/meta-harness/isolated-subagent.mjs','packages/meta-harness/child-output.mjs',
        'packages/meta-harness/output-context.mjs','packages/meta-harness/captured-subprocess.mjs','packages/meta-harness/Dockerfile',
        'packages/meta-harness/capabilities.json','packages/meta-harness/development-dependencies.json','packages/meta-harness/runtime-package.json','packages/meta-harness/runtime-package-lock.json','package.json','package-lock.json']
    groups['native-runtime']=source_group(source,support)
    files={k:v for group in groups.values() for k,v in group.items()}
    lock=json.loads((source/'package-lock.json').read_text());package='@deepseek-ai/dsh-sdk-minimal';framework=lock['packages']['node_modules/'+package]
    system=system_prompt({**config,'stopPolicy':'stop-review-v1'})
    system['text']+='\n\n原生工作环境（meta-runtime-v2）：\n使用原生文件、搜索、编辑、终端、任务、技能与会话工具开展研究。插件目录位于 /work/plugins，分析笔记位于 /work/analysis；候选工具接受插件目录相对路径。完整材料索引为 /evidence/index.json，终端完整输出索引为 /outputs/index.json。返回预览不等于文件全文，按路径自行检索。普通研究子代理使用原生 spawn，与主 Meta 共享授权文件和持久会话存储；cwd 遵循原生指定/继承规则。使用 send_message 追问或续接，interrupt_agent 中断当前工作；恢复后先用 list_agents 和会话查询核对原子任务，再决定继续，不盲目重做未知副作用。研究子代理无额外五分钟总时限，仍受原活动截止和预算限制。停止审查者独立隔离。业务工具直接传对象参数，写操作带稳定的 idempotencyKey；请求结果未知时先核对后台记录，不重复创建。candidate_retain 的预期选择修订来自 campaign_status.selectionRevision。report_get_facts 取得不可变事实快照后，report_save 提交 analysis 或带摘要的 analysisFile、factsId 与 expectedReportRevision（首次为 0）；每个报告修订永久保留。\n'
    system.update(version='meta-system-v8',sha256=hashlib.sha256(system['text'].encode()).hexdigest())
    from .meta_contracts import binding
    document={'toolContract':binding(),'version':VERSION,'composition':composition,'files':files,'groups':{k:{'id':digest(v),'files':v} for k,v in groups.items()},
        'framework':{'package':package,**{k:framework[k] for k in ['version','resolved','integrity']}},
        'systemPrompt':system,'reviewerPrompt':(plugin/'reviewer.md').read_text(),
        'runnerImage':prepare_image(source,data),'stopPolicy':'stop-review-v1','lockSha256':files['package-lock.json'],
        'capabilities':json.loads((plugin/'capabilities.json').read_text()),'runtimeVersion':'meta-runtime-v2','recovery':{'additionalAttempts':2,'delaysSeconds':[2,10]},'delegationVersion':'native-research-v1','hostBoundary':'shared activity research Runner; independently isolated stop review; host-bound channels'}
    id=digest(document);root=data/'meta-compositions'/id;root.mkdir(parents=True,exist_ok=True)
    objects=data/'meta-objects/sha256';objects.mkdir(parents=True,exist_ok=True)
    for rel,sha in files.items():
        target=objects/sha
        if not target.exists():
            content=(source/rel).read_bytes()
            if hashlib.sha256(content).hexdigest()!=sha:raise Refused('Meta source changed during freeze')
            fd,name=tempfile.mkstemp(dir=objects,prefix='.publishing-')
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(content)
                os.chmod(name,0o444)
                try:os.link(name,target)
                except FileExistsError:pass
            finally:os.unlink(name)
        if target.is_symlink() or file_hash(target)!=sha:raise Refused('Meta content object corrupted')
    from src.evidence.files import atomic_json
    atomic_json(root/'manifest.json',{**document,'id':id})
    verify(data,{'id':id},source)
    return {'id':id,'version':VERSION,'plugins':composition['plugins'],'preset':composition['id'],'runnerImage':document['runnerImage'],
        'toolContract':document['toolContract'],'lockSha256':document['lockSha256'],'stopPolicy':document['stopPolicy'],'framework':document['framework']}

def verify(data,reference,source):
    id=reference['id']
    if not re.fullmatch(r'[0-9a-f]{64}',id):raise Refused('Invalid Meta composition identity')
    data=Path(data);source=Path(source);file=data/'meta-compositions'/id/'manifest.json'
    document=json.loads(file.read_text())
    if document.get('version')!=VERSION or document.get('id')!=id or digest({k:v for k,v in document.items() if k!='id'})!=id:raise Refused('Meta manifest integrity mismatch')
    if file_hash(source/'package-lock.json')!=document['lockSha256']:raise Refused('Restore matching Meta dependency lock first')
    root=data/'cache/meta-runtimes'/id;root.mkdir(parents=True,exist_ok=True)
    # Materialize only verified blobs. Cache loss never loses a saved composition.
    for rel,sha in document['files'].items():
        relative=safe_relative(rel)
        if not re.fullmatch(r'[0-9a-f]{64}',sha):raise Refused('Invalid Meta blob identity')
        blob=data/'meta-objects/sha256'/sha
        if blob.is_symlink() or not blob.is_file() or file_hash(blob)!=sha:raise Refused('Meta content integrity mismatch: '+rel)
        target=root/relative
        if any(p.is_symlink() for p in [target,*target.parents] if p!=root and root in p.parents):raise Refused('Meta cache path escapes root')
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            try:os.link(blob,target)
            except OSError:shutil.copyfile(blob,target)
        if file_hash(target)!=sha:raise Refused('Meta cache integrity mismatch: '+rel)
    (root/'manifest.json').write_text(encoded(document)+'\n')
    modules=root/'node_modules'
    if not modules.exists():modules.symlink_to(source/'node_modules',target_is_directory=True)
    elif not modules.is_symlink() or modules.resolve()!=(source/'node_modules').resolve():raise Refused('Unexpected Meta dependency cache')
    return root,document
