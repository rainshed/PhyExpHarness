from src.execution.host.storage_layout import lock_path
"""Frozen, reconstructible reference adapter runtime; credentials stay outside it."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import fcntl
import sys
from pathlib import Path
from ..store import Refused,encoded
from ..model_access import control_only, environment as model_environment
from .catalog import atomic_private,HARNESS,uses_codex_host

def freeze_runtime(source,data):
    source=Path(source);data=Path(data);files={}
    for file in (source/'src/execution').rglob('*'):
        if file.is_file() and '__pycache__' not in file.parts and file.suffix in ('.py','.mjs','.json','.yml'):
            files[file.relative_to(source).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
    files['package-lock.json']=hashlib.sha256((source/'package-lock.json').read_bytes()).hexdigest()
    id=hashlib.sha256(encoded(files).encode()).hexdigest();root=data/'reference-runtimes'/id
    for name,sha in files.items():
        target=root/name
        if not target.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,target)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise Refused('Reference runtime integrity mismatch')
    atomic_private(root/'manifest.json',{'id':id,'files':files})
    if not (root/'node_modules').exists():(root/'node_modules').symlink_to(source/'node_modules',target_is_directory=True)
    return id

def verify_runtime(data,id,source=None):
    if not isinstance(id,str) or len(id)!=64 or any(c not in '0123456789abcdef' for c in id):raise Refused('Invalid reference runtime identity')
    root=Path(data)/'reference-runtimes'/id;manifest=json.loads((root/'manifest.json').read_text())
    if hashlib.sha256(encoded(manifest['files']).encode()).hexdigest()!=id:raise Refused('Reference manifest changed')
    for name,sha in manifest['files'].items():
        file=root/name
        if not file.resolve().is_relative_to(root.resolve()) or file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=sha:raise Refused('Reference runtime changed: '+name)
    if source is not None:
        from ..meta_native_composition import compatible_dependency_lock
        if not compatible_dependency_lock(Path(data),Path(source),manifest['files']['package-lock.json']):raise Refused('Restore matching reference runtime dependencies')
    return root

def image_for(service,trial,bundle):
    return subprocess.check_output(['docker','image','inspect',bundle['runnerImage'],'--format','{{.Id}}'],text=True).strip()

def prepare_image(source,data,harness,base,log):
    spec=HARNESS[harness];context=Path(source)/'templates/reference'/harness
    files={name:hashlib.sha256((context/name).read_bytes()).hexdigest() for name in ('package.json','package-lock.json')}
    key=hashlib.sha256(encoded({'base':base,'files':files}).encode()).hexdigest()
    tag='phyexp-reference:'+harness+'-'+key[:20]
    mutex=Path(data)/'reference-image-locks';mutex.mkdir(parents=True,exist_ok=True)
    with (lock_path(mutex/(key+'.lock'))).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        check=subprocess.run(['docker','image','inspect',tag,'--format','{{.Id}}'],capture_output=True,text=True)
        if check.returncode:
            with tempfile.TemporaryDirectory(prefix='phyexp-reference-image-') as temp:
                root=Path(temp)
                for name in files:shutil.copyfile(context/name,root/name)
                # Native SDK dependencies live at the normal module root. CLI packages
                # have separate roots and PATH entries, with their entire lock pinned.
                install='/opt/phyexp' if harness=='dsh-standard' else '/opt/reference-cli'
                base_tag='phyexp-reference:base-'+base.removeprefix('sha256:')
                subprocess.run(['docker','image','tag',base,base_tag],check=True)
                (root/'Dockerfile').write_text(f'FROM {base_tag}\nUSER root\nWORKDIR {install}\nCOPY package.json package-lock.json ./\nRUN npm ci --no-audit --no-fund\nENV PATH="{install}/node_modules/.bin:${{PATH}}"\nUSER node\nWORKDIR /work\n')
                with Path(log).open('w') as output:subprocess.run(['docker','build','-t',tag,temp],stdout=output,stderr=subprocess.STDOUT,check=True,timeout=600)
        image=subprocess.check_output(['docker','image','inspect',tag,'--format','{{.Id}}'],text=True).strip()
        return {'image':image,'imageTag':tag,'lockDigest':files['package-lock.json'],'baseImage':base}

def prepare_images(service,campaign,bundle):
    c=service.store.get('campaigns',campaign)
    if not c['config'].get('referencePolicy',{}).get('harnessEnabled'):return
    if bundle.get('schemaVersion')==3:
        from .process import prepare_harness_base
        bundle=prepare_harness_base(service,campaign)
    base=subprocess.check_output(['docker','image','inspect',bundle['runnerImage'],'--format','{{.Id}}'],text=True).strip()
    for harness in c['config']['referencePolicy']['harnessRefs']:
        receipt=prepare_image(service.source,service.data,harness,base,service.data/'campaigns'/campaign/(harness+'-image.log'))
        with service.store.connection(True) as db:
            current=service.store._get(db,'campaigns',campaign)
            current['config']['referenceBindings']['harnesses'][harness].update(receipt)
            service.store._save(db,'campaigns',current)

def launch(service,trial):
    from src.execution.bundle.manifest import verify
    from src.execution.host.models import campaign_route
    from src.execution.host.network import provider_environment
    candidate=service.store.get('candidates',trial['candidateId']);bundle=verify(candidate['bundlePath'])
    runtime=verify_runtime(service.data,trial['reference']['runtime'],service.source)
    c=service.store.get('campaigns',trial['campaignId']);cfg=c['config'];ref=trial['reference']
    output=service.data/'trials'/trial['launchId'];lease,token=service.lease(c['id'],'solver',trial['deadline'],trial['id'])
    harness=ref.get('harnessRef');model=ref.get('modelRef');frozen=None
    if model:
        frozen=service.references.catalog.binding(model)
        if hashlib.sha256(encoded(frozen).encode()).hexdigest()!=ref['modelBindingDigest']:raise Refused('Reference model changed')
    reference_env={};execution_candidate=candidate
    if bundle.get('schemaVersion')==3:
        if harness:
            execution_candidate={**candidate,**cfg['referenceBindings']['baseBundle']}
        else:
            from .process import bind_model
            execution,reference_env=bind_model(service,c['id'],candidate,frozen,model)
            execution_candidate={**candidate,**execution}
        bundle=verify(execution_candidate['bundlePath'])
        if bundle.get('schemaVersion')==3:
            from ..execution_cache import prepare_runtime
            runtime=prepare_runtime(execution_candidate['bundlePath'],service.data/'cache')
        ref={**ref,'candidateBundleId':candidate['bundleId'],'executionBundleId':bundle['id']}
        trial=service.store.trial_update(trial['id'],executionBundle={k:execution_candidate[k] for k in ('bundleId','bundlePath','executionContract')},reference=ref)
    spec={**ref,'native':frozen,'credentialFile':str(service.references.catalog.root/'credentials'/(model+'.json')) if model else None,
          'fixedSolver':{**{k:v for k,v in json.loads((Path(candidate['bundlePath'])/'recipe.json').read_text()).items() if k in ('provider','model','reasoningEffort','maxTokens')},'providerConfig':campaign_route(cfg,'solver')}}
    private=service.data/'campaigns'/c['id']/'reference-private'/(trial['id']+'.json');atomic_private(private,spec)
    image=(json.loads((Path(execution_candidate['bundlePath'])/'recipe.json').read_text())['processResources']['brokerImage'] if bundle.get('schemaVersion')==3 else cfg['referenceBindings']['harnesses'].get(harness,{}).get('image') if harness else image_for(service,trial,bundle))
    if not image:raise Refused('Reference Harness image was not prepared')
    env=dict(provider_environment() if model else service.providers.environment(cfg['solver']['provider'],campaign_route(cfg,'solver')),
             **model_environment(service.base_url,lease['id'],token,cfg),**reference_env,
             PHYEXP_LAUNCH_ID=trial['launchId'],PHYEXP_REFERENCE_SPEC=str(private),PHYEXP_REFERENCE_IMAGE=image)
    args=[sys.executable,'-m','src.execution.host.single_run','--bundle',execution_candidate['bundlePath'],'--quantum-harbor',str(service.quantum),
          '--task',trial['task'],'--output',str(output),'--deadline',str(trial['deadline']),'--timeout',str(max(1,trial['deadline']-service.store.clock()))]
    if not control_only(cfg):args+=['--soft-token-limit',str(cfg['softTokenLimit'] or 'none')]
    lock=cfg.get('taskImageLocks',{}).get(trial['task'])
    if cfg.get('taskImagePolicy') and not lock:raise Refused('Reference task images unavailable')
    if lock:
        lockfile=service.data/'campaigns'/c['id']/(trial['task']+'.image-lock.json');atomic_private(lockfile,lock);args+=['--task-image-lock',str(lockfile)]
    trial=service.store.trial_update(trial['id'],output=str(output),leaseId=lease['id'],executionEntry=str(runtime/'src/execution/host/single_run.py'))
    log=service.data/'trials'/(trial['launchId']+'.supervisor.log');log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w') as stream:process=subprocess.Popen(args,cwd=runtime,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    service.children[trial['id']]=process
    return service.store.trial_update(trial['id'],state='running',pid=process.pid)

def preflight(service,campaign):
    from .policy import effective
    c=service.store.get('campaigns',campaign);policy=effective(c)
    if not policy['modelEnabled'] and not policy['harnessEnabled']:return
    binding=c['config'].get('referenceBindings',{})
    verify_runtime(service.data,binding['runtime'],service.source)
    if policy['modelEnabled']:
        for id in policy['modelRefs']:
            value=service.references.catalog.binding(id)
            if hashlib.sha256(encoded(value).encode()).hexdigest()!=binding['models'][id]['digest']:raise Refused('Reference native binding changed')
            if uses_codex_host(value):
                # Validate the current host login without copying it into the catalog or calling a model.
                auth_module=(service.source/'src/execution/host/chatgpt_auth.mjs').as_uri()
                script='import {createChatGPTCredentials} from '+json.dumps(auth_module)+';try{createChatGPTCredentials().dispose()}catch{process.exitCode=1}'
                result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,timeout=15)
                if result.returncode:raise Refused('Reference Codex host login unavailable or expiring; refresh the host login')
            elif not (service.references.catalog.root/'credentials'/(id+'.json')).is_file():raise Refused('Reference native credential unavailable')
    if policy['harnessEnabled']:
        for id in policy['harnessRefs']:
            image=binding['harnesses'][id].get('image')
            if not image:raise Refused('参考 Harness 运行环境尚未准备完成：'+binding['harnesses'][id].get('name',id)+'。请查看后台动态中的准备状态。')
            actual=subprocess.check_output(['docker','image','inspect',image,'--format','{{.Id}}'],text=True).strip()
            if actual!=image:raise Refused('Reference Harness image identity mismatch')
