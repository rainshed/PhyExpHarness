from src.execution.host.log_store import read_log
"""Independent control service: owns scheduling, recovery and admission; never executes generated code."""
import hashlib
import fcntl
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .store import Store,Refused,Conflict,identity,encoded,comparison_issues,retention_rule_description,META_RETENTION_RULE
from .knowledge import KnowledgePack
from .image_identity import resolve as resolve_image_identity
from .operations import workspace_path,read_workspace,write_workspace,execute_workspace
from src.execution.bundle.freeze import freeze,verify
from src.execution.bundle.manifest import resolve as resolve_bundle,infrastructure_identity,read_plugins
from .execution_cache import prepare_runtime
from .result_collection import read_summary, projection
from src.execution.host.single_run import cleanup,task_image_sources,write_json
from .task_images import POLICY as TASK_IMAGE_POLICY,prepare_task_images,sources_digest,verify_locks
from .runner_images import prepare_runner_image
from src.execution.host.network import network_preflight
from src.execution.host.models import campaign_route
from src.execution.host.failure import public_failure
from .meta_status import meta_status
from src.evidence.library import EvidenceLibrary
from src.evidence.objects import POLICY as STORAGE_POLICY
from src.evidence.diagnostics import trial_diagnostics
from src.evidence.outcomes import evaluation, DEFAULT_RULE
from src.evidence.materials import Materials,snapshot_tasks
from .meta_context import activity_state
from .meta_composition import freeze as freeze_meta, verify as verify_meta
from .stop_policy import GOAL_POLICY, CONTROLLED_POLICIES
from .stop_review import StopRuntime
from .processes import reap_children
from . import resource_planning as planning
from src.execution.host.task_time import POLICY as BENCHMARK_TIME, benchmark_time, read_task_time, verify_task_time
from src.reporting.reports import Reports
from src.exporting.project import export_project
from src.exporting.validate import relocate

class ControlService:
    def __init__(self,source,data,quantum_harbor,base_url,launch_trial=None):
        self.source=Path(source).resolve();self.data=Path(data).resolve();self.data.mkdir(parents=True,exist_ok=True);self.data.chmod(0o700)
        self.quantum=Path(quantum_harbor).resolve();self.base_url=base_url
        self.store=Store(self.data/'control.sqlite');self.evidence=EvidenceLibrary(self.store,self.data);self.reports=Reports(self.store,self.data)
        from .deletion import ActivityAccess,Deletions
        self.access=ActivityAccess();self.deletions=Deletions(self)
        self.knowledge=KnowledgePack(self.source/'knowledge/plugin-sdk/reference','0.2.1-rc.2')
        from .research import Research
        self.research=Research(self.store,self.data)
        from src.evidence.adoptions import Adoptions
        self.adoptions=Adoptions(self)
        self.materials=Materials(self);self.stop_runtime=StopRuntime(self)
        from .meta_api import MetaAPI
        self.meta_api=MetaAPI(self)
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='phyexp-build');self.operations={};self.children={}
        self.operation_lock=threading.Lock()
        for row in self.store.list('operations'):
            if row['state']=='running' and not self.store.deletion(row['campaignId']):
                row.update(state='failed',error='Control process restarted during build; no experiment was launched by this operation',finishedAt=time.time());self.store.put('operations',row)
                with self.store.connection(True) as db:self.store._event(db,row['campaignId'],'operation_finished',operationId=row['id'],state='failed')
        self.launch_trial_override=launch_trial;self.tick_lock=threading.Lock();self.meta_driver=None
        token_file=self.data/'user-token'
        if not token_file.exists():token_file.write_text(secrets.token_urlsafe(32));token_file.chmod(0o600)
        self.user_token=token_file.read_text().strip()
        from .provider_settings import ProviderSettings
        self.providers=ProviderSettings(self)
        from .reference.service import References
        self.references=References(self)
        from .storage import Storage
        self.storage=Storage(self)
    def authenticate(self,token):
        if secrets.compare_digest(token,self.user_token):return {'role':'user'}
        digest=hashlib.sha256(token.encode()).hexdigest()
        for lease in self.store.list('leases'):
            if secrets.compare_digest(digest,lease['tokenHash']):
                if lease.get('revoked') or time.time()>=lease['deadline']:raise Refused('Lease expired')
                return lease
        raise Refused('Authentication failed')
    def lease(self,campaign,role,deadline,trial_id=None):
        token=secrets.token_urlsafe(32)
        row=self.store.put('leases',{'id':identity('lease'),'campaignId':campaign,'role':role,'trialId':trial_id,
            'deadline':deadline,'tokenHash':hashlib.sha256(token.encode()).hexdigest(),'revoked':False})
        return row,token
    def workspace(self,campaign):
        self.store.writable(campaign)
        self.store.get('campaigns',campaign)
        path=self.data/'campaigns'/campaign/'workspace';path.mkdir(parents=True,exist_ok=True);return path
    def knowledge_for(self,campaign):
        config=self.store.get('campaigns',campaign)['config']
        candidates=self.store.list('candidates',campaign)
        target=None
        if candidates and Path(candidates[0]['bundlePath'],'bundle.json').is_file():
            target=verify(candidates[0]['bundlePath'])
        id=config.get('knowledgePackId') or (target or {}).get('knowledgePackId')
        if not id:id=self.knowledge.manifest['id']
        if not isinstance(id,str) or len(id)!=64 or any(c not in '0123456789abcdef' for c in id):raise Refused('Invalid knowledge pack identity')
        path=self.data/'knowledge-packs'/id
        if not path.exists() and id==self.knowledge.manifest['id']:path=self.knowledge.path
        if not path.exists():raise Refused('Version-matched knowledge pack unavailable')
        pack=KnowledgePack(path,(target or {}).get('dshVersion','0.2.1-rc.2'),(target or {}).get('profileDigest'))
        if pack.manifest['id']!=id:raise Refused('Knowledge pack identity mismatch')
        return pack
    def _operation(self,campaign,kind,payload,fn):
        if hasattr(self,'storage') and not self.storage.permit(campaign,'build'):raise Refused('存储空间不足，暂不启动构建；释放空间后重试。')
        row=self.store.put('operations',{'id':identity('operation'),'campaignId':campaign,'kind':kind,'payload':payload,'state':'running','startedAt':time.time()})
        def work():
            with self.access.enter():
                if self.store.deletion(campaign):return
                try:result=fn();row.update(state='finished',result=result)
                except Exception as error:
                    row.update(state='failed',error=str(error))
                    if getattr(error,'check_files',None):row['files']=error.check_files
                if self.store.deletion(campaign):return
                row['finishedAt']=time.time()
                try:
                    self.store.put('operations',row)
                    with self.store.connection(True) as db:self.store._event(db,campaign,'operation_finished',operationId=row['id'],state=row['state'])
                except Conflict:
                    if not self.store.deletion(campaign):raise
        self.operations[row['id']]=self.pool.submit(work)
        return {'operationId':row['id'],'state':'running'}
    def create(self,config,key,model_revision=None,source='operator'):
        self.store.check_create_key(key)
        from src.execution.host.container_runtime import preflight
        preflight(config.get('tasks', []))
        if not isinstance(key,str) or not 1<=len(key)<=200:raise Refused('Idempotency key required')
        # Server-owned defaults are outside the idempotency request. Cache changes
        # and create replays must never replace an existing Campaign's snapshot.
        with self.providers.lock:
            with self.providers.connection() as db:
                catalog=self.providers.document(db)
            # A successful create replay uses its original snapshot, even after a catalog edit.
            with self.store.connection() as db:
                replay=db.execute("SELECT payload FROM commands WHERE campaign='global' AND kind='create' AND key=?",(key,)).fetchone()
            config=dict(config)
            if not replay:
                if config.get('resourcePolicy',planning.POLICY)!=planning.POLICY:
                    raise Refused('New activities require benchmark resource planning')
                if config.get('trialTimeSeconds') is not None:
                    raise Refused('求解时限由 benchmark 决定，请移除单次时限设置。')
                if 'taskTimeLimits' in config or 'executionTimePolicy' in config:
                    raise Refused('Benchmark time configuration is server-owned')
            if not replay or json.loads(replay['payload']).get('resourcePolicy'):
                config.setdefault('resourcePolicy',planning.POLICY)
            if planning.enabled(config) and 'configurationSources' not in config:
                config['configurationSources']=json.loads(replay['payload'])['configurationSources'] if replay else {k:{'source':source if config.get(k) is not None else 'unset' if k in ('maxRounds','maxTrials','softTokenLimit','trialTimeSeconds') else 'platform_default',
                    'value':config.get(k)} for k in planning.LIMITS}
            if planning.enabled(config) and 'taskEvaluationRule' not in config:
                # A replay must use the original request defaults, including pre-v4 creates.
                original=json.loads(replay['payload']) if replay else {}
                if not replay or 'taskEvaluationRule' in original:
                    config['taskEvaluationRule']=original.get('taskEvaluationRule',DEFAULT_RULE)
            if model_revision is not None and not replay:self.providers.check_revision(catalog,model_revision)
            # The generated reference can change while this long-lived service runs.
            # Freeze and verify the current files before persisting a new Campaign;
            # retries keep their original pack instead of silently rebinding it.
            knowledge=None
            if not replay:
                try:
                    knowledge=KnowledgePack(self.source/'knowledge/plugin-sdk/reference','0.2.1-rc.2').snapshot(self.data/'knowledge-packs')
                except (ValueError,OSError) as error:
                    raise Refused('开发资料包尚未准备好；请完成资料构建后重试。此次未创建活动。详情：'+str(error)) from error
            reference_defaults=self.references.freeze(config) if not replay else {}
            time_defaults={'executionTimePolicy':{'version':BENCHMARK_TIME,'scope':'Benchmark agent phase; startup and verification are separate.'},
                'taskTimeLimits':{task:read_task_time(self.quantum,task) for task in config['tasks']}} if not replay else {}
            composition=freeze_meta(self.source,self.data,{**config,**time_defaults,'stopPolicy':GOAL_POLICY}) if not replay else None
            campaign=self.store.create(config,key,defaults={**reference_defaults,'storagePolicy':STORAGE_POLICY,'metaComposition':composition,'stopPolicy':GOAL_POLICY,'knowledgePackId':knowledge.manifest['id'] if knowledge else None,'materialVersion':1,
                **time_defaults,
                'modelCatalogRevision':catalog['revision'],
                'taskImagePolicy':TASK_IMAGE_POLICY,'taskImageLocks':{},'taskImageSourcesDigest':sources_digest(task_image_sources(self.quantum))})
        id=campaign['id'];self.workspace(id)
        with self.operation_lock:
            if campaign['config'].get('materialVersion')==1:
                self.knowledge_for(id).snapshot(self.data/'knowledge-packs')
                snapshot_tasks(self,id)
            if not self.store.list('candidates',id) and not self.store.list('operations',id):
                self._operation(id,'prepare_h0',{},lambda:self._prepare_h0(id))
        return self.status(id)
    def task_catalog(self):
        from .store import PUBLIC_TASKS
        tasks=[]
        for task in PUBLIC_TASKS:
            try:tasks.append({'id':task,**read_task_time(self.quantum,task)})
            except (ValueError,OSError) as error:tasks.append({'id':task,'unavailable':str(error)})
        return {'tasks':tasks}
    def _prepare_h0(self,campaign):
        c=self.store.get('campaigns',campaign)
        if c['config'].get('taskImagePolicy')==TASK_IMAGE_POLICY:
            log=self.data/'campaigns'/campaign/'checks'/'task-images.log'
            try:
                locks=prepare_task_images(self.quantum,c['config']['tasks'],self.data/'task-runtime-locks',log,
                    expected_sources_digest=c['config']['taskImageSourcesDigest'])
                with self.store.connection(True) as db:
                    current=self.store._get(db,'campaigns',campaign)
                    if current['state']!='draft':raise Refused('Campaign no longer awaiting environment preparation')
                    if current['config'].get('taskImageLocks'):raise Refused('Campaign task images are already frozen')
                    current['config']['taskImageLocks']=locks
                    self.store._save(db,'campaigns',current)
                    self.store._event(db,campaign,'task_images_prepared',tasks=c['config']['tasks'],log=str(log))
            except Exception as error:
                raise Refused('Task image preparation failed: '+str(error)+'; log: '+str(log)) from error
        candidate=self.build_candidate(campaign,[],'H0：固定执行基线')
        if c['config'].get('referenceBindings'):
            from .reference.runtime import prepare_images
            prepare_images(self,campaign,verify(candidate['bundlePath']))
        return candidate
    def _verify_task_images(self,config):
        if benchmark_time(config):
            for task in config['tasks']:verify_task_time(self.quantum,task,config['taskTimeLimits'][task])
        if config.get('taskImagePolicy')==TASK_IMAGE_POLICY:
            try:verify_locks(self.quantum,config['tasks'],config.get('taskImageLocks',{}))
            except ValueError as error:raise Refused(str(error)) from error
    def list_status(self):
        return [{**self.store.status(c['id']), 'metaStatus':meta_status(self.store.list('meta_sessions',c['id'])),
                 **({'deletion':self.deletions.public(self.store.deletion(c['id']))} if c['state']=='deleting' else {})}
                for c in self.store.list('campaigns')]
    def status(self,campaign):
        value=self.store.status(campaign)
        if value['state']=='deleting':
            return {**value,'deletion':self.deletions.public(self.store.deletion(campaign)),
                    **{k:[] for k in ['candidates','batches','trials','reports','exports','evidence','operations','metaSessions']},
                    'tables':{'versions':[],'plugins':[],'trials':[]}}
        value.update(candidates=self.store.list('candidates',campaign),batches=self.store.list('batches',campaign),
            trials=trial_diagnostics(self.store.list('trials',campaign),self.data,value['config']),operations=self.store.list('operations',campaign),
            reports=[{k:r[k] for k in ['id','kind','batchId','createdAt','analysisRevision','status']} for r in self.store.list('reports',campaign)],
            stopReviews=self.store.list('stop_reviews',campaign),metaObservations=self.store.list('meta_observations',campaign),
            exports=self.store.list('exports',campaign),metaSessions=self.store.list('meta_sessions',campaign),metaQuestions=self.store.list('meta_questions',campaign),
            evidence=[{k:v for k,v in e.items() if k!='path'} for e in self.store.list('evidence',campaign)])
        value['references']=self.references.status(campaign)
        value['metaStatus']=meta_status(value['metaSessions'])
        value['executionProtection']=self.execution_policy(campaign)
        value['comparisonIssues']=comparison_issues(value['trials'])
        value['retentionRuleDescription']=retention_rule_description(value['config'])
        value['selectionDecisions']=[{k:r.get(k) for k in ['id','candidateId','previousCandidateId','createdAt','summary','limitations']}|{'detailsAvailable':True} for r in self.store.list('selection_decisions',campaign)]
        value['researchRevision']=[len(self.store.list(t,campaign)) for t in ['research_records','research_links','source_adoptions']]
        if value['config'].get('storagePolicy')==STORAGE_POLICY:value['storage']=self.storage.view(campaign)
        value['observedAt']=self.store.clock()
        value['taskEvaluation']=evaluation(value['trials'],value['config']['tasks'],value['candidates'],value['config'])
        value['tables']=self.reports.tables(campaign,context=value)
        return value
    def execution_policy(self,campaign):
        candidates=self.store.list('candidates',campaign)
        baseline=candidates[0] if candidates else {}
        if not baseline or not (Path(baseline['bundlePath'])/'bundle.json').is_file():return None
        resolved=resolve_bundle(baseline['bundlePath'])
        policy=resolved.assets.get('src/execution/host/stream-policy.json')
        result=json.loads(policy.read_text()) if policy else None
        if result and benchmark_time(self.store.get('campaigns',campaign)['config']):
            result.update(version='benchmark-stream-v1',requestTimeoutMs=None,streamIdleTimeoutMs=None)
        return result
    def build_candidate(self,campaign,selections,description,parent=None,display_name=None,check_only=False,research_refs=None):
        self.store.writable(campaign)
        c=self.store.get('campaigns',campaign)
        recipe=json.loads((self.source/'recipes/h0-sol.json').read_text())
        recipe.update(c['config']['solver']);recipe['modules']=[]
        if 'reasoningEffort' not in c['config']['solver']:recipe.pop('reasoningEffort',None)
        recipe['providerConfig']=campaign_route(c['config'],'solver')
        recipe['maxTokens']=recipe['providerConfig']['models'][0].get('maxTokens',8192)
        if benchmark_time(c['config']):
            recipe['timePolicy']=BENCHMARK_TIME
            recipe.pop('agentTimeoutSec',None);recipe.pop('commandTimeoutSec',None)
        else:
            recipe.pop('timePolicy',None);recipe['commandTimeoutSec']=300
            recipe['agentTimeoutSec']=c['config']['trialTimeSeconds'] or (c['config']['wallTimeSeconds']+(c['config']['drainGraceSeconds'] if c['config']['stopMode']=='drain' else 0) if planning.enabled(c['config']) else 3600)
        chosen=[]
        for selected in selections:
            directory=workspace_path(self.workspace(campaign),selected['path'])
            if not directory.is_dir():raise Refused('Plugin directory missing')
            # Reject explicit routing by exposed task ID. This check is evidence, not proof of generalization.
            for file in directory.rglob('*.mjs'):
                if file.is_symlink():raise Refused('Plugin symlink forbidden')
                text=file.read_text()
                if any(task in text for task in c['config']['tasks']):raise Refused('Task-specific selector detected in plugin source')
            chosen.append({'path':str(directory),'config':selected.get('config',{})})
        existing=self.store.list('candidates',campaign)
        base=verify(existing[0]['bundlePath']) if existing else None
        bundle=freeze(self.source,self.data/'objects/sha256',recipe,chosen,self.knowledge_for(campaign).manifest,
                      legacy=bool(base and base.get('schemaVersion',1)==1),
                      on_publish=lambda path,kind:self.store.track_artifact(campaign,path,kind))
        if existing:
            if infrastructure_identity(base)!=infrastructure_identity(bundle['manifest']):
                raise Refused('Fixed infrastructure changed; start a new Campaign for a comparable baseline')
        directory=Path(bundle['path']);logs=self.data/'campaigns'/campaign/'checks'/identity('check');logs.mkdir(parents=True)
        locks=self.data/'locks';locks.mkdir(exist_ok=True)
        try:
            with (locks/(bundle['id']+'.lock')).open('a') as lock,(logs/'installation.log').open('w') as log:
                fcntl.flock(lock,fcntl.LOCK_EX)
                runtime=prepare_runtime(directory,self.data/'cache',log)
                if bundle['manifest'].get('schemaVersion',1)==1:
                    marker=directory/'node_modules/.phyexp-install'
                    lock_hash=hashlib.sha256((directory/'package-lock.json').read_bytes()).hexdigest()
                    if not marker.exists() or marker.read_text()!=lock_hash:
                        subprocess.run(['npm','ci','--ignore-scripts','--no-audit','--no-fund'],cwd=directory,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
                        marker.write_text(lock_hash)
                runner_image=prepare_runner_image(runtime,self.data/'runner-runtime-locks',log)
                subprocess.run(['node',str(runtime/'src/execution/bundle/check.mjs'),str(directory),str(logs)],
                    cwd='/tmp',stdout=log,stderr=subprocess.STDOUT,check=True,timeout=45)
            check=json.loads((logs/'assembly.json').read_text());check.update(evidence=str(logs),generalization='not_verified',runnerImagePreparation=runner_image)
        except Exception as error:
            if c['config'].get('metaComposition',{}).get('version')=='meta-composition-v2':
                error.check_files=[self.meta_api.files.publish(campaign,'check:'+logs.name+':'+p.name,p.read_bytes(),kind='check',source={'archive':p.name},version=bundle['id']) for p in sorted(logs.iterdir()) if p.is_file()]
            raise
        if check_only:
            files=[self.meta_api.files.publish(campaign,'check:'+logs.name+':'+p.name,p.read_bytes(),kind='check',source={'archive':p.name},version=bundle['id']) for p in sorted(logs.iterdir()) if p.is_file()]
            return {'checkId':logs.name,'status':check['status'],'bundleId':bundle['id'],'files':files,'trialCreated':False}
        row=self.store.candidate(campaign,bundle,description,parent,check,research_refs)
        if display_name and isinstance(display_name,str):
            row['displayName']=display_name.strip()[:80];row=self.store.put('candidates',row)
        return row
    def control(self,campaign,action,key,expected_revision=None,changes=None):
        self.store.writable(campaign)
        c=self.store.get('campaigns',campaign)
        if action in ('start','resume') and c['config'].get('referenceBindings') and not self.launch_trial_override:
            from .reference.runtime import preflight as reference_preflight
            reference_preflight(self,campaign)
        if action=='start':
            candidates=self.store.list('candidates',campaign)
            h0=next((x for x in candidates if not x['plugins'] and x['check']['status']=='passed'),None)
            if not h0:raise Refused('H0 assembly is not ready')
            self._verify_task_images(c['config'])
            if c['state']=='draft' and not self.launch_trial_override:
                seen=set()
                for role in ['solver','meta']:
                    model=c['config'][role]
                    route=campaign_route(c['config'],role)
                    endpoint=(model['provider'],json.dumps(route,sort_keys=True))
                    if endpoint in seen:continue
                    seen.add(endpoint)
                    checked=network_preflight(model,route,environment=self.providers.environment(model['provider'],route))
                    with self.store.connection(True) as db:self.store._event(db,campaign,'network_preflight',provider=model['provider'],**checked)
        if action=='resume':
            self._verify_task_images(c['config'])
            if c['config'].get('metaComposition'):
                verify_meta(self.data,c['config']['metaComposition'],self.source)
        result=self.store.control(campaign,action,key,expected_revision,changes)
        if action=='start' and (not planning.enabled(c['config']) or c.get('resourcePlan')):self.store.submit(campaign,h0['id'],c['config']['tasks'],1,'system-baseline')
        # User stop ends experiments but leaves the remaining Meta budget available for reports.
        if action=='pause' and self.meta_driver:self.meta_driver.interrupt(campaign,action)
        if action=='stop':
            for t in self.store.runs(campaign):
                if t['state'] in ['launching','running']:self.stop_trial(t,'user_stop')
        return result
    def _process_alive(self,pid,output):
        if not isinstance(pid,int):return False
        result=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
        return result.returncode==0 and str(output) in result.stdout
    def references_launch(self,trial):
        from .reference.runtime import launch
        return launch(self,trial)
    def _launch(self,trial):
        if trial.get('reference') and not self.launch_trial_override:
            return self.references_launch(trial)
        candidate=self.store.get('candidates',trial['candidateId']);bundle=Path(candidate['bundlePath']);manifest=verify(bundle)
        output=self.data/'trials'/trial['launchId']
        lease,token=self.lease(trial['campaignId'],'solver',trial['deadline'],trial['id'])
        trial=self.store.trial_update(trial['id'],output=str(output),leaseId=lease['id'])
        if self.launch_trial_override:
            process=self.launch_trial_override(trial)
        else:
            runtime=prepare_runtime(bundle,self.data/'cache')
            trial=self.store.trial_update(trial['id'],executionEntry=str(runtime/'run.py'))
            frozen=self.store.get('campaigns',trial['campaignId'])['config']
            env=dict(self.providers.environment(frozen['solver']['provider'],campaign_route(frozen,'solver')),PHYEXP_ACCOUNTING_URL=self.base_url+'/accounting/'+lease['id'],PHYEXP_ACCOUNTING_TOKEN=token,
                PHYEXP_LAUNCH_ID=trial['launchId'])
            args=[sys.executable,str(runtime/'run.py'),*(['--bundle',str(bundle)] if manifest.get('schemaVersion')==2 else []),'--quantum-harbor',str(self.quantum),'--task',trial['task'],
                '--output',str(output),'--deadline',str(trial['deadline']),'--timeout',str(max(1,trial['deadline']-time.time())),
                '--soft-token-limit',str(self.store.get('campaigns',trial['campaignId'])['config']['softTokenLimit'] or 'none')]
            config=self.store.get('campaigns',trial['campaignId'])['config']
            lock=config.get('taskImageLocks',{}).get(trial['task'])
            if config.get('taskImagePolicy')==TASK_IMAGE_POLICY and not lock:
                raise Refused('Task images are not prepared: '+trial['task'])
            if lock:
                lock_file=self.data/'campaigns'/trial['campaignId']/(trial['task']+'.image-lock.json')
                write_json(lock_file,lock)
                args+=['--task-image-lock',str(lock_file)]
            log=self.data/'trials'/(trial['launchId']+'.supervisor.log');log.parent.mkdir(parents=True,exist_ok=True)
            with log.open('w') as stream:process=subprocess.Popen(args,env=env,cwd='/tmp',stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        self.children[trial['id']]=process
        return self.store.trial_update(trial['id'],state='running',pid=process.pid)
    def stop_trial(self,trial,reason):
        if trial.get('stopRequestedAt'):return
        self.store.trial_update(trial['id'],stopReason=reason,stopRequestedAt=time.time())
        if trial.get('leaseId'):
            lease=self.store.get('leases',trial['leaseId']);lease['revoked']=True;self.store.put('leases',lease)
        if self._process_alive(trial.get('pid'),trial.get('output','')):
            os.kill(trial['pid'],signal.SIGTERM)
    def _reconcile_usage(self,trial):
        if not trial.get('leaseId'):return
        for file in Path(trial['output']).glob('harbor/*/phyexp/gateway-audit.jsonl'):
            for line in read_log(file).decode('utf-8').splitlines():
                try:row=json.loads(line)
                except json.JSONDecodeError:continue
                if row.get('type')!='settled':continue
                try:self.store.settle(trial['campaignId'],trial['leaseId'],row['id'],(row.get('usage') or {}).get('totalTokens'),not row.get('finish') or row.get('finish',{}).get('kind')=='error' or not row.get('usage'),host_audit=True)
                except (KeyError,ValueError):pass
        self.store.mark_unknown(trial['leaseId'])
    def _collect(self,trial):
        output=Path(trial['output'])
        summary=read_summary(trial,self.store.get('candidates',trial['candidateId']));self._reconcile_usage(trial)
        state='finished' if summary.get('pipelineStatus')=='completed' else 'failed'
        changes=dict(state=state,score=summary.get('officialReward'),outcome=summary.get('taskOutcome'),
            **({k:summary.get(k) for k in ['failureContract','requestRecovery']} if summary.get('failureContract') else {}),
            failure=summary.get('failure'),scoringStatus=summary.get('scoringStatus','completed' if summary.get('officialReward') is not None else 'unknown'),
            usage=summary.get('usage',{}),fixture=summary.get('fixture',False),finishedAt=time.time(),
            stopReason=summary.get('stopReason') if summary.get('resultCollection') else trial.get('stopReason') or summary.get('stopReason'),summary=summary,
            resultCollection=summary.get('resultCollection'))
        provenance_path=output/'provenance.json'
        if provenance_path.exists():
            provenance=json.loads(provenance_path.read_text())
            images=[]
            for file in output.glob('harbor/*/phyexp/container-images.txt'):
                images.extend(sorted(line.split(' ',1)[1] for line in file.read_text().splitlines() if ' ' in line))
            changes['comparisonContext']={'taskSourcesDigest':hashlib.sha256(encoded(provenance.get('quantumHarbor',{}).get('sourceHashes')).encode()).hexdigest(),
                'runnerImageId':provenance.get('runnerImageId'),'taskImageIds':images}
            if trial.get('effectiveConditions'):
                changes['comparisonContext']['executionConditions']={k:trial['effectiveConditions'].get(k) for k in ('trialTimeSeconds','actualTimeSeconds','frozenTrialCeilingSeconds')}
                if trial['effectiveConditions'].get('timePolicy')==BENCHMARK_TIME:
                    changes['comparisonContext']['executionConditions']=trial['effectiveConditions']['benchmarkTime']
            if provenance.get('taskImageLock'):
                changes['comparisonContext']['verifierImageId']=provenance['taskImageLock']['images']['verifier']
            try:
                proof=resolve_image_identity(provenance.get('runnerImageId'),self.data/'runtime-image-proofs')
                changes['comparisonContext']['runnerExecutionManifest']=proof['executionDigest']
                changes['runnerImageProof']=proof
            except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError):
                pass # Keep strict raw-image comparison when proof is unavailable.
        items=self.evidence.ingest(trial,summary)
        t=self.store.trial_update(trial['id'],**changes)
        c=self.store.get('campaigns',trial['campaignId'])
        if not trial.get('reference') and c['config'].get('retentionRule')!=META_RETENTION_RULE and c['retainedCandidateId'] is None and t['score'] is not None:
            self.store.retain(c['id'],t['candidateId'],'首个有官方结果的参考版本；不表示已验证泛化。',[items[0]['id']])
        return t
    def recollect(self,trial_id):
        # Serialize with scheduling/collection. This endpoint never runs Solver or verifier.
        with self.tick_lock:
            trial=self.store.run(trial_id);campaign=trial['campaignId']
            if self.store.get('campaigns',campaign)['state'] not in ['paused','finished','failed']:
                raise Refused('Pause the Campaign before recovering results')
            if trial['state'] not in ['finished','failed','unknown']:
                raise Refused('Only ended Trials can be recollected')
            try:summary=read_summary(trial,self.store.get('candidates',trial['candidateId']))
            except OSError as error:raise Refused('Collection evidence is unavailable: '+str(error)) from error
            if not summary.get('resultCollection'):
                raise Refused('No supported result collection correction for this Trial')
            if trial.get('resultCollection')==summary['resultCollection']:
                return {'status':'already_recovered','trialId':trial_id,'score':trial.get('score')}
            changes=projection(summary)
            # Immutable before/after receipt, including original timestamps and unknown usage.
            receipt={'trialId':trial_id,'campaignId':campaign,'before':trial,'changes':changes}
            digest=hashlib.sha256(encoded(receipt).encode()).hexdigest()
            path=self.data/'result-recoveries'/digest
            path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():path.write_text(encoded(receipt));path.chmod(0o444)
            items=self.evidence.ingest(trial,summary)
            with self.store.connection(True) as db:
                if self.store._get(db,self.store.run_table(trial_id),trial_id)!=trial:raise Refused('Trial changed during result recovery')
                current=self.store._get(db,'campaigns',campaign)
                if current['state'] not in ['paused','finished','failed']:raise Refused('Campaign resumed during result recovery')
                self.store._save_run(db,{**trial,**changes})
                self.store._event(db,campaign,'trial_result_recollected',trialId=trial_id,
                    correction=summary['resultCollection'],previousScore=trial.get('score'),score=changes['score'],
                    receiptSha256=digest,evidenceRefs=[items[0]['id']])
            return {'status':'recovered','trialId':trial_id,'score':changes['score'],'receiptSha256':digest}
    def _reconcile_trial(self,trial):
        output=Path(trial.get('output',self.data/'trials'/trial['launchId']))
        conditions=trial.get('effectiveConditions',{})
        if conditions.get('timePolicy')==BENCHMARK_TIME and conditions.get('solverDeadline') is None:
            for file in output.glob('harbor/*/phyexp/timing.json'):
                try:timing=json.loads(file.read_text())
                except (OSError,json.JSONDecodeError):continue
                trial=self.store.trial_update(trial['id'],effectiveConditions={**conditions,
                    **{k:timing[k] for k in ('solverStartedAt','solverDeadline')}})
                break
        if (output/'summary.json').is_file() and (output/'archive-manifest.json').is_file():
            return self._collect({**trial,'output':str(output)})
        process=self.children.get(trial['id'])
        alive=process.poll() is None if process else self._process_alive(trial.get('pid'),output)
        if not alive and not trial.get('pid'):
            candidate=self.store.get('candidates',trial['candidateId'])
            listing=subprocess.run(['ps','-Ao','pid,command'],capture_output=True,text=True).stdout
            for line in listing.splitlines():
                if trial.get('executionEntry',str(Path(candidate['bundlePath'])/'run.py')) in line and str(output) in line:
                    pid=int(line.strip().split()[0])
                    self.store.trial_update(trial['id'],state='running',pid=pid,output=str(output));return
        if not alive and (output/'supervisor.json').exists():
            info=json.loads((output/'supervisor.json').read_text());pid=info.get('pid')
            if self._process_alive(pid,output):
                self.store.trial_update(trial['id'],state='running',pid=pid,output=str(output));return
        if not alive:
            # A launching claim is never silently retried after a crash window.
            cleanup(output);self._reconcile_usage({**trial,'output':str(output)})
            return self._failed_trial(trial,'supervisor_lost_start_not_repeated',state='unknown',output=str(output))
        if time.time()>=trial['deadline'] and not trial.get('stopRequestedAt'):
            self.stop_trial(trial,'campaign_deadline' if conditions.get('timePolicy')==BENCHMARK_TIME else 'trial_deadline')
        if trial.get('stopRequestedAt') and time.time()-trial['stopRequestedAt']>15:
            if self._process_alive(trial.get('pid'),output):os.kill(trial['pid'],signal.SIGKILL)
            cleanup(output)
    def _failed_trial(self,trial,reason,**extra):
        failure=public_failure({'code':reason,'stage':'startup' if reason=='startup_failure' else 'supervision','source':'controller'})
        changes={'state':'failed','score':None,'stopReason':reason,'finishedAt':time.time(),'failure':failure,'scoringStatus':'unknown',**extra}
        self.evidence.add(trial['campaignId'],trial['id'],'lifecycle',json.dumps({'trialId':trial['id'],**changes},ensure_ascii=False),{'authority':'controller','officialScore':None})
        return self.store.trial_update(trial['id'],**changes)
    def tick(self):
        self.deletions.tick()
        try:
            with self.access.enter():self._tick()
        except Conflict:
            if not self.access.cleaning:raise
    def _tick(self):
        if not self.tick_lock.acquire(blocking=False):return
        try:
            # Finished Campaigns can still own supervisors that exited after collection.
            reap_children(self.children,self.store,'trials',{'finished','failed','cancelled','unknown'})
            if self.meta_driver:self.meta_driver.reap_children()
            self.storage.schedule()
            for campaign in self.store.list('campaigns'):
                id=campaign['id']
                if campaign['state'] in ['draft','finished','failed','deleting']:continue
                for trial in self.store.runs(id):
                    if trial['state'] in ['launching','running']:
                        if trial.get('referenceStopPending'):self.stop_trial(trial,'reference_plugin_disabled')
                        try:self._reconcile_trial(trial)
                        except Exception as error:self.store.trial_update(trial['id'],lastCollectionError=str(error))
                c=self.store.status(id);cfg=c['config'];now=time.time()
                if c['state']=='running' and not self.store.list('batches',id) and (not planning.enabled(cfg) or c.get('resourcePlan')):
                    h0=next((x for x in self.store.list('candidates',id) if not x['plugins'] and x['check']['status']=='passed'),None)
                    if h0:
                        try:self.store.submit(id,h0['id'],cfg['tasks'],1,'system-baseline')
                        except Refused:
                            if not planning.enabled(cfg):raise
                            # Meta still needs its turn to revise an infeasible plan.
                            pass
                usage=c['usage']
                if cfg['softTokenLimit'] is not None and not usage['inflightReservedTokens'] and usage['confirmedTokens']+usage['unknownReservedTokens']+300000>cfg['softTokenLimit']-cfg['reserveTokens']:
                    self.store.close_admission(id,'token_threshold')
                if now>=c['deadline']-(0 if planning.enabled(cfg) else cfg['reserveSeconds']) and c['state']!='closing':self.store.close_admission(id,'time_limit')
                if c['state']=='running' and self.storage.permit(id,'trial'):
                    trial=self.store.claim(id)
                    if trial:
                        try:self._launch(trial)
                        except Exception as error:self._failed_trial(trial,'startup_failure',error=str(error))
                c=self.store.status(id)
                if c['explorationClosed'] and c['counts']['activeTrials']==0 and c['counts']['reservedTrials']==0:
                    self.store.close_admission(id,c['stopReason'] or 'completed',False)
                if now>=c['deadline']:
                    for t in self.store.runs(id):
                        if t['state'] in ['launching','running'] and (cfg['stopMode']=='strict' or now>=t['deadline']):self.stop_trial(t,'campaign_deadline')
                    if self.meta_driver:self.meta_driver.interrupt(id,'campaign_deadline')
                pressure=self.storage.view(id)
                if pressure['critical'] and cfg.get('storagePolicy')==STORAGE_POLICY:
                    for t in self.store.runs(id):
                        if t['state'] in ('launching','running') and not t.get('stopRequestedAt'):self.stop_trial(t,'storage_capacity')
                    if self.meta_driver:self.meta_driver.interrupt(id,'storage_capacity')
                if self.meta_driver:self.meta_driver.tick(id)
                elif c['state']=='closing' and c['counts']['activeTrials']==0:
                    self.store.finalize(id);self.reports.status_summary(id,'达到活动上限；Meta 分析尚未完成。')
        finally:self.tick_lock.release()
    def export(self,campaign,candidate):
        self.store.writable(campaign)
        c=self.store.get('candidates',candidate)
        if c['campaignId']!=campaign:raise Refused('Candidate unavailable')
        prior=next((x for x in self.store.list('exports',campaign) if x['candidateId']==candidate),None)
        if prior:return prior
        export_id=identity('export');self.store.track_artifact(campaign,self.data/'exports'/export_id,'export')
        result=export_project(c['bundlePath'],self.data/'exports',export_id=export_id);result.update(campaignId=campaign,candidateId=candidate)
        return self.store.put('exports',result)
    def validate_export(self,id):
        with self.operation_lock:
            row=self.store.get('exports',id)
            self.store.writable(row['campaignId'])
            if row.get('relocationValidation')=='passed' and row.get('validationEvidence'):
                proof=json.loads(Path(row['validationEvidence']).read_text())
                if proof['archiveSha256']==hashlib.sha256(Path(row['archive']).read_bytes()).hexdigest() and proof['bundleId']==row['bundleId']:
                    return {'state':'finished','result':row}
            active=next((o for o in self.store.list('operations',row['campaignId']) if o['kind']=='export_relocation' and o['state']=='running' and o['payload']['exportId']==id),None)
            if active:return {'operationId':active['id'],'state':'running'}
            def work():
                destination=self.data/'export-checks'/identity('relocated export')
                self.store.track_artifact(row['campaignId'],destination,'export_check')
                try:
                    proof=relocate(row,destination)
                    row.update(relocationValidation='passed',validationEvidence=proof['evidence'])
                except Exception:
                    row['relocationValidation']='failed';self.store.put('exports',row);raise
                return self.store.put('exports',row)
            return self._operation(row['campaignId'],'export_relocation',{'exportId':id},work)
    def meta_call(self,campaign,operation,args):
        c=self.store.get('campaigns',campaign)
        if c['state'] in ['draft','finished','failed']:raise Refused('Meta session is not active')
        if not isinstance(args,dict):raise Refused('Operation input must be an object')
        if operation=='sdk_search':return self.knowledge_for(campaign).search(**args)
        if operation=='sdk_read':return self.knowledge_for(campaign).read(**args)
        if operation=='sdk_inspect':return self.knowledge_for(campaign).inspect(**args)
        if operation in ['materials_list','materials_search','materials_read']:
            allowed={'ref','offset','limit'} if operation=='materials_read' else {'kind','task','candidateId','batchId','offset','limit'}|({'query'} if operation=='materials_search' else set())
            if set(args)-allowed:raise Refused('Unknown material query fields')
            if operation=='materials_read' and 'ref' not in args:raise Refused('Material ref required')
            if operation=='materials_search' and 'query' not in args:raise Refused('Material query required')
            return getattr(self.materials,operation.removeprefix('materials_'))(campaign,**args)
        if operation=='campaign_status':
            if args.get('view','summary')=='summary':return activity_state(self,campaign)
            if args.get('view')!='full':raise Refused('Unknown status view')
            status=self.status(campaign)
            for t in status['trials']:
                t.pop('summary',None)
                if 'taskSources' in t.get('comparisonContext',{}):
                    context=t['comparisonContext'];context['taskSourcesDigest']=hashlib.sha256(encoded(context.pop('taskSources')).encode()).hexdigest()
            return status
        if operation=='campaign_plan_update':
            return self.store.update_plan(campaign,args['changes'],args['reason'],args['idempotencyKey'],args['expectedPlanRevision'],source='meta')
        if operation=='trial_conditions_accept':
            return self.store.accept_trial_conditions(campaign,args['trialId'],args['trialTimeSeconds'],args['idempotencyKey'],args['reason'])
        if operation=='workspace_read':
            if args.get('candidateId'):
                selected=self.store.get('candidates',args['candidateId'])
                if selected['campaignId']!=campaign:raise Refused('Candidate unavailable')
                return read_plugins(selected['bundlePath'],args['path'])
            return read_workspace(self.workspace(campaign),args['path'])
        if operation=='candidate_list':
            candidates=self.store.list('candidates',campaign)
            stats=evaluation(trial_diagnostics(self.store.list('trials',campaign),self.data,c['config']),c['config']['tasks'],candidates,c['config'])
            return [{**candidate,'taskEvaluation':stats['byCandidate'][candidate['id']]} for candidate in candidates]
        if operation=='evidence_list':
            rows=self.store.list('evidence',campaign)
            if args.get('batchId'):
                ids={t['id'] for t in self.store.runs(campaign) if t['batchId']==args['batchId']};rows=[e for e in rows if e['trialId'] in ids]
            return [{k:v for k,v in e.items() if k!='path'} for e in rows]
        if operation=='evidence_read':return self.evidence.read(campaign,**args)
        if operation=='report_save':
            batch=args.get('batchId');analysis={k:v for k,v in args.items() if k!='batchId'}
            record=self.reports.save(campaign,analysis,batch)
            return {k:record[k] for k in ['id','kind','batchId','analysisRevision','status','factsSha256']}
        if operation=='candidate_retain':
            if c['config'].get('retentionRule')==META_RETENTION_RULE:
                candidate=self.store.get('candidates',args['candidateId'])
                if candidate['campaignId']!=campaign:raise Refused('Candidate unavailable')
                try:bundle=verify(candidate['bundlePath'])
                except (OSError,ValueError) as error:raise Refused('Frozen candidate integrity check failed') from error
                if bundle['id']!=candidate['bundleId']:raise Refused('Frozen candidate identity mismatch')
            return self.store.retain(campaign,args['candidateId'],args.get('reason'),args.get('evidenceRefs'),
                **{key:args.get(key) for key in ['tradeoffs','limitations','reconsiderWhen','expectedSelectionRevision']})
        if operation=='export_create':return self.export(campaign,args['candidateId'])
        if operation=='campaign_finish':
            reason=args.get('reason')
            if not isinstance(reason,str) or not reason.strip() or len(reason)>16000:raise Refused('A concise evidence-based stop reason is required')
            return self.store.control(campaign,'finish','meta-finish-'+hashlib.sha256(encoded(args).encode()).hexdigest(),changes=args if c['config'].get('stopPolicy') in CONTROLLED_POLICIES else {'reason':reason})
        if c['state']!='running' or c['explorationClosed']:raise Refused('Search writes closed; evidence and reports remain available')
        if operation=='workspace_write':return write_workspace(self.workspace(campaign),**args)
        if operation=='workspace_exec':
            candidates=self.store.list('candidates',campaign)
            bundle=verify(candidates[0]['bundlePath'])
            return execute_workspace(self.workspace(campaign),args['command'],bundle['runnerImage'])
        if operation=='candidate_freeze':
            with self.operation_lock:
                key=args.get('idempotencyKey')
                prior=next((x for x in self.store.list('operations',campaign) if key and x['kind']=='freeze' and x['payload'].get('idempotencyKey')==key),None)
                if prior:
                    if prior['payload']!=args:raise Refused('Freeze idempotency key conflicts with prior input')
                    return {'operationId':prior['id'],'state':prior['state'],'result':prior.get('result'),'error':prior.get('error')}
                return self._operation(campaign,'freeze',args,lambda:self.build_candidate(campaign,args['plugins'],args['description'],args.get('parent'),args.get('displayName'),research_refs=args.get('researchRefs')))
        if operation=='batch_submit':
            if planning.enabled(c['config']) and not self.store.list('batches',campaign):
                if args['tasks']!=c['config']['tasks'] or args['repeats']!=1 or self.store.get('candidates',args['candidateId'])['plugins']:
                    raise Refused('First batch must cover the H0 baseline once on all selected tasks')
            return self.store.submit(campaign,args['candidateId'],args['tasks'],args['repeats'],args['idempotencyKey'],args.get('execution'))
        raise Refused('Meta capability unavailable')
