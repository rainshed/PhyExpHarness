"""Optional reference capabilities, immutable bindings and bounded Meta selection."""
import hashlib
import json
from pathlib import Path
from ..store import Refused,Conflict,encoded
from ..meta_api import page
from src.execution.host.models import campaign_route
from .catalog import Catalog,HARNESS,uses_codex_host
from ..model_access import control_only, check_config
from .policy import DEFAULT,validate,effective,enabled,TERMINAL,release_cancelled_slots
from src.evidence.outcomes import outcome_summary
from src.evidence.diagnostics import trial_diagnostics

class References:
    def __init__(self,service):self.service=service;self.store=service.store;self.catalog=Catalog(service)
    def freeze(self,config):
        if 'referenceBindings' in config:raise Refused('Reference bindings are server-owned')
        policy=validate(config.get('referencePolicy',DEFAULT))
        if not policy['modelEnabled'] and not policy['harnessEnabled']:return {}
        catalog=self.catalog.public()
        if policy['modelEnabled'] and policy.get('catalogRevision')!=catalog['revision']:raise Conflict('Native model catalog changed; refresh it')
        if any(not catalog['plugins'][axis] for axis in ('model','harness') if policy[axis+'Enabled']):raise Refused('Selected reference package is not installed')
        models={}
        for id in policy['modelRefs'] if policy['modelEnabled'] else []:
            row=next((m for m in catalog['models'] if m['id']==id),None)
            if not row or row.get('unavailable'):raise Refused('Native reference model unavailable: '+id)
            models[id]=row
        if any(id not in HARNESS for id in policy['harnessRefs']):raise Refused('Unknown reference Harness')
        from .runtime import freeze_runtime
        runtime=freeze_runtime(self.service.source,self.service.data)
        return {'referenceBindings':{'models':models,'harnesses':{id:HARNESS[id] for id in policy['harnessRefs'] if policy['harnessEnabled']},'runtime':runtime}}
    def compatibility(self,c,model,harness):
        if harness not in HARNESS:return {'state':'unsupported','reason':'尚未登记此 Harness 适配器'}
        if model:
            snapshot=self.catalog.binding(model);call=snapshot['call'];raw=snapshot['config']
            profile=raw.get('providers',{}).get(call['provider'],raw)
            wire='anthropic' if snapshot['adapter']=='deepseek-api-key' or profile.get('api')=='anthropic-messages' else 'responses' if profile.get('api')=='openai-responses' else 'native'
            auth=snapshot.get('credentialRef') is not None
            if uses_codex_host(snapshot):wire='responses';auth=True
        else:
            route=campaign_route(c['config'],'solver');wire='anthropic' if route['adapter']=='deepseek' or route.get('api')=='anthropic-messages' else 'responses' if route.get('api')=='openai-responses' else 'native'
            auth=route['auth']['type']=='api-key'
        if harness=='dsh-standard':return {'state':'supported','reason':'使用冻结的原生模型配置与完整 SDK 标准模式'}
        if not model and harness=='codex' and route['auth']['type']=='codex':
            return {'state':'supported','reason':'保留固定 Solver 的 Codex 订阅通道；凭据仅在宿主，全部请求纳入共享账本'}
        if not auth:return {'state':'unsupported','reason':'此适配器目前需要明确的 API Key 模型通道；原生账户认证可在 DeepSeek Harness 中使用'}
        if wire!=HARNESS[harness]['wire']:return {'state':'unsupported','reason':'模型服务未提供 '+HARNESS[harness]['wire']+' 接口，不能保持原模型直接运行'}
        from .compatibility import external_settings_issue
        issue=external_settings_issue(snapshot if model else None,c['config'].get('solver',{}),route if not model else None)
        if issue:return {'state':'unverified','reason':issue}
        return {'state':'supported','reason':'接口兼容；执行时锁定所选模型与调用设置'}
    def status(self,campaign,args=None):
        c=self.store.get('campaigns',campaign);policy=effective(c);bindings=c['config'].get('referenceBindings',{})
        batches=self.store.list('reference_batches',campaign);runs=trial_diagnostics(self.store.list('reference_runs',campaign),self.service.data,c['config'])
        for row in runs:row.pop('summary',None)
        if args and args.get('batchId'):
            batches=[b for b in batches if b['id']==args['batchId']]
            if not batches:raise Refused('Reference batch unavailable')
            runs=[r for r in runs if r['batchId']==args['batchId']]
        matrix=[]
        for model in [None,*policy['modelRefs']]:
            for harness in policy['harnessRefs']:
                try:check=self.compatibility(c,model,harness)
                except (ValueError,KeyError,OSError):check={'state':'temporarily-unavailable','reason':'Frozen model snapshot unavailable'}
                matrix.append({'modelRef':model,'harnessRef':harness,**check})
        groups={}
        for run in runs:
            key=encoded({k:run['reference'].get(k) for k in ('mode','modelRef','harnessRef','executionBundleId')})
            groups.setdefault(key,[]).append(run)
        comparisons=[{'binding':json.loads(key),'evaluation':outcome_summary(rows,c['config']['tasks'],c['config'])} for key,rows in groups.items()]
        return {'evidenceIndex':'/evidence/index.json','comparisons':comparisons,'policy':policy,'bindings':bindings,'compatibility':matrix,'batches':page(batches,args or {}),
                'runs':page(runs,args or {}),'groups':{mode:[r['id'] for r in runs if r['reference']['mode']==mode] for mode in ('model-reference','harness-reference','joint-reference')},
                'comparisonLimitations':['Reference runs do not change primary candidate scores or stability claims.','Joint changes cannot attribute improvement to one dimension.']}
    def call(self,campaign,operation,args):
        axis=operation.split('_')[1];action=operation.split('_')[2]
        c=self.store.get('campaigns',campaign);policy=effective(c)
        if not enabled(policy,[axis]):raise Refused('Reference plugin disabled')
        if action in ('list','status'):return self.status(campaign,args)
        if action=='cancel':return self.cancel(campaign,args,axis)
        model=args.get('modelRef');harness=args.get('harnessRef') if axis=='harness' else None
        required=['model','harness'] if model and harness else [axis]
        if not enabled(policy,required):raise Refused('Joint reference requires both plugins')
        mode='joint-reference' if len(required)==2 else axis+'-reference'
        if harness:
            compatibility=self.compatibility(c,model,harness)
            if compatibility['state']!='supported':raise Refused(compatibility['reason'])
        candidates=self.store.list('candidates',campaign)
        selected=next((x for x in candidates if x['id']==args.get('candidateId')),None) if axis=='model' else next((x for x in candidates if not x['plugins'] and x['check']['status']=='passed'),None)
        if selected is None:raise Refused('Checked execution candidate unavailable')
        if model:
            binding=self.catalog.binding(model)
            digest=hashlib.sha256(encoded(binding).encode()).hexdigest()
            if digest!=c['config'].get('referenceBindings',{}).get('models',{}).get(model,{}).get('digest'):raise Refused('Frozen native model integrity mismatch')
        if model:
            if not harness and c['config'].get('executionContract')=='harbor-process-v1':
                from .process import model_route
                model_route(binding)
            recipe=Path(selected.get('bundlePath',''))/'recipe.json'
            solver=json.loads(recipe.read_text()) if recipe.is_file() else c['config']['solver']
            original={k:solver.get(k) for k in ('provider','model','reasoningEffort','maxTokens')}
            changed=[k for k,v in original.items() if binding['call'].get(k)!=v]
            model_difference={'state':'changed' if changed else 'unverified','fields':changed,'reason':'Native provider snapshot differs in identity/settings' if changed else 'Same call identity; cross-configuration provider equivalence is not certified'}
        else:model_difference={'state':'unchanged','fields':[]}
        ref={'mode':mode,'requiredCapabilities':required,'modelRef':model,'harnessRef':harness,
             'policyRevision':args['expectedPolicyRevision'],'researchQuestion':args['researchQuestion'],
             'modelBindingDigest':digest if model else None,'executionBundleId':selected['bundleId'],
             'requestedDimensions':(['model'] if model else [])+(['harness'] if harness else []),
             'changedDimensions':{'model':model_difference,'harness':{'state':'changed' if harness else 'unchanged','executionBundleId':selected['bundleId'],'referenceHarness':harness}},
             'runtime':c['config']['referenceBindings']['runtime']}
        # The request remains a single pair. The controller never expands a Cartesian sweep.
        return self.store.submit(campaign,selected['id'],args['tasks'],args['repeats'],args['idempotencyKey'],args.get('execution'),reference=ref)
    def cancel(self,campaign,args,axis=None):
        with self.store.connection(True) as db:
            prior=self.store._idem(db,campaign,'reference-cancel',args['idempotencyKey'],args)
            if prior:return prior
            c=self.store._get(db,'campaigns',campaign)
            if effective(c)['revision']!=args['expectedPolicyRevision']:raise Conflict('Reference policy revision changed')
            batch=self.store._get(db,'reference_batches',args['batchId'])
            if batch['campaignId']!=campaign or axis and axis not in batch['reference']['requiredCapabilities']:raise Refused('Reference batch unavailable')
            for row in self.store._list(db,'reference_runs',campaign):
                if row['batchId']==batch['id'] and row['state']=='reserved':
                    row.update(state='cancelled',stopReason='reference_cancelled');self.store._save(db,'reference_runs',row)
            self.store._finish_batches(db,campaign)
            release_cancelled_slots(self.store,db,c)
            self.store._event(db,campaign,'reference_batch_cancelled',batchId=batch['id'])
            return self.store._remember(db,campaign,'reference-cancel',args['idempotencyKey'],args,self.store._get(db,'reference_batches',batch['id']))
    def update(self,campaign,policy,key,expected,stop_running=False):
        if type(expected) is not int or type(stop_running) is not bool:raise Refused('Invalid policy revision or stopRunning flag')
        policy=validate(policy);stops=[]
        with self.store.connection(True) as db:
            payload={'policy':policy,'expectedRevision':expected,'stopRunning':stop_running}
            prior=self.store._idem(db,campaign,'reference-policy',key,payload)
            if prior:return prior
            c=self.store._get(db,'campaigns',campaign);old=effective(c);original=c['config'].get('referencePolicy',DEFAULT)
            if control_only(c['config']):check_config({'referencePolicy':policy})
            if old['revision']!=expected:raise Conflict('Reference policy revision changed')
            if c['state'] in ('finished','failed'):raise Refused('Reference policy is frozen after closeout')
            for axis in ('model','harness'):
                if policy[axis+'Enabled'] and not original[axis+'Enabled']:raise Refused('Plugin was not frozen for this activity; create a new activity to enable it')
                if set(policy[axis+'Refs'])-set(original[axis+'Refs']):raise Refused('Cannot widen frozen reference allowlist')
            updated={**policy,'revision':expected+1};c['referencePolicy']=updated
            for row in self.store._list(db,'reference_runs',campaign):
                ref=row['reference'];allowed=enabled(updated,ref['requiredCapabilities']) and (not ref.get('modelRef') or ref['modelRef'] in policy['modelRefs']) and (not ref.get('harnessRef') or ref['harnessRef'] in policy['harnessRefs'])
                if allowed and ref['mode']=='joint-reference' and policy['selectionMode']=='pinned-pairs':allowed={'modelRef':ref['modelRef'],'harnessRef':ref['harnessRef']} in policy['pairs']
                if not allowed and row['state']=='reserved':
                    row.update(state='cancelled',stopReason='reference_policy_changed');self.store._save(db,'reference_runs',row)
                elif not allowed and stop_running and row['state'] in ('launching','running'):
                    row['referenceStopPending']=True;self.store._save(db,'reference_runs',row);stops.append(row)
                    if row.get('leaseId'):
                        lease=self.store._get(db,'leases',row['leaseId']);lease['revoked']=True;self.store._save(db,'leases',lease)
            self.store._save(db,'campaigns',c);self.store._finish_batches(db,campaign)
            release_cancelled_slots(self.store,db,c)
            self.store._event(db,campaign,'reference_policy_changed',policy=updated,stopRunning=stop_running)
            self.store._remember(db,campaign,'reference-policy',key,payload,updated)
        if self.service.meta_driver:self.service.meta_driver.interrupt(campaign,'reference_policy_changed')
        for row in stops:self.service.stop_trial(row,'reference_plugin_disabled')
        return updated
