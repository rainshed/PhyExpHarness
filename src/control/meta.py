from src.execution.host.log_store import read_log
"""Persisted Meta sessions and event delivery. No scientific improvement procedure is prescribed."""
import json
import os
import signal
import subprocess
import time
import fcntl
from pathlib import Path
from .store import identity,Refused
from .meta_context import system_prompt,startup_context,activity_state
from .processes import reap_children
from .meta_composition import verify as verify_meta
from src.execution.host.models import campaign_route
from . import resource_planning as planning
from .meta_recovery import recovery

def native_config(c):return c['config'].get('metaComposition',{}).get('version')=='meta-composition-v2'

class MetaDriver:
    def __init__(self,service):self.service=service;self.store=service.store;self.children={}
    def _save_session(self,row):
        # Runtime agent receipts have a separate writer; heartbeat/state updates must not erase them.
        with self.store.connection(True) as db:
            current=self.store._get(db,'meta_sessions',row['id'])
            excluded={'agents','revision'}|({'cursor','deliveredCursor'} if current.get('runtimeVersion')=='meta-runtime-v2' else set())
            current.update({k:v for k,v in row.items() if k not in excluded})
            return self.store._save(db,'meta_sessions',current)
    def reap_children(self):
        reap_children(self.children,self.store,'meta_sessions',{'completed','failed','interrupted','recovering','needs_attention'})
    def start(self,campaign):
        # The persisted row and process launch are one host-owned admission window.
        self.store.get('campaigns',campaign)
        lockfile=self.service.data/'campaigns'/campaign/'meta-start.lock';lockfile.parent.mkdir(parents=True,exist_ok=True)
        with lockfile.open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return
            return self._start(campaign)
    def _start(self,campaign):
        c=self.store.status(campaign);now=time.time()
        if now>=c['deadline'] or c['state'] not in ['running','closing']:return
        previous=self.store.list('meta_sessions',campaign)
        if any(s['state'] in ['starting','running','waiting'] for s in previous):return
        native=native_config(c);last=previous[-1] if previous else None
        prompt=startup_context(self.service,campaign)
        frozen=None
        if c['config'].get('metaComposition'):
            frozen,composition=verify_meta(self.service.data,c['config']['metaComposition'],self.service.source)
            system=composition['systemPrompt']
        else:system=system_prompt(c['config'])
        pack=self.service.knowledge_for(campaign)
        lease,token=self.service.lease(campaign,'meta',c['deadline'])
        id=identity('meta');logs=self.service.data/'campaigns'/campaign/'meta-sessions'/id;logs.mkdir(parents=True)
        cursor=self.store.last_event(campaign)
        if native and last:cursor=last.get('cursor',0)
        route=campaign_route(c['config'],'meta')
        config={'id':id,'campaignId':campaign,'leaseId':lease['id'],'model':{**c['config']['meta'],'maxTokens':route['models'][0].get('maxTokens',8192)},
            'providerConfig':route,
            'deadline':c['deadline'],'softTokenLimit':c['config']['softTokenLimit'],'cursor':cursor,
            'knowledgePackId':pack.manifest['id'],'systemPrompt':system,'prompt':json.dumps(prompt,ensure_ascii=False,separators=(',',':'))}
        if frozen:
            from .reference.policy import effective
            config.update(metaCompositionRoot=str(frozen),metaCompositionId=composition['id'],referencePolicy=effective(c))
        if native:
            files=self.service.meta_api.files;files.refresh(campaign)
            prompt['runtimeCapabilities']=files.publish(campaign,'runtime:capabilities',json.dumps(composition['capabilities']),kind='activity',source='frozen-meta-capabilities',version=composition['id'])
            work=self.service.data/'campaigns'/campaign/'meta-work'
            session_root=self.service.data/'campaigns'/campaign/'meta-native-session'
            for name in ['plugins','analysis','checks','agents']:(work/name).mkdir(parents=True,exist_ok=True)
            session_root.mkdir(parents=True,exist_ok=True)
            resume=bool(last and not last.get('summary',{}).get('resumeFailed'))
            prompt['resumption']={'newSession':not resume,'history':'Native persisted session and /materials; reconcile metaRequests before writes'}
            config.update(nativeSessionId=last.get('nativeSessionId',last['id']) if resume else id,
                resumeSession=resume,previousSessionId=last['id'] if last else None,workRoot=str(work),sessionRoot=str(session_root),
                filesRoot=str(files.directory(campaign)),pluginWorkspace=str(self.service.workspace(campaign)))
            config['prompt']=json.dumps({'context':prompt,'paths':{'plugins':'/work/plugins','analysis':'/work/analysis','evidence':'/evidence/index.json','outputs':'/outputs/index.json','session':'/session'},
                'recovery':{'previousSessionId':config['previousSessionId'],'mode':'native-resume' if resume else 'linked-new-session' if last else 'new-session','unknownOperations':'Reconcile recorded operations before submitting again.'}},ensure_ascii=False)
        file=logs/'context.json';file.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
        row=self.store.put('meta_sessions',{'id':id,'campaignId':campaign,'leaseId':lease['id'],'state':'starting','output':str(logs),
            'startedAt':now,'deadline':c['deadline'],'cursor':cursor,'knowledgePackId':config['knowledgePackId'],
            'compositionId':c['config'].get('metaComposition',{}).get('id'),'promptVersion':system['version'],'systemPromptSha256':system['sha256'],
            **({'runtimeVersion':'meta-runtime-v2','nativeSessionId':config['nativeSessionId'],'previousSessionId':config['previousSessionId'],
                'recoveryAttempt':last.get('recovery',{}).get('nextAttempt',0) if last else 0} if native else {})})
        env=dict(self.service.providers.environment(c['config']['meta']['provider'],route),PHYEXP_CONTROL_URL=self.service.base_url,PHYEXP_META_TOKEN=token)
        with (logs/'worker.log').open('w') as log:
            process=subprocess.Popen(['node',str((frozen or self.service.source)/('src/control/meta_worker_native.mjs' if native else 'src/control/meta_worker.mjs')),str(file)],
                env=env,cwd=self.service.source,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        self.children[id]=process;row.update(state='running',pid=process.pid);self._save_session(row)
        with self.store.connection(True) as db:self.store._event(db,campaign,'meta_started',sessionId=id,resumed=bool(previous))
    def interrupt(self,campaign,reason):
        for row in self.store.list('meta_sessions',campaign):
            if row['state'] in ['starting','running','waiting'] and not row.get('stopRequestedAt'):
                if self.service._process_alive(row.get('pid'),row['output']):os.kill(row['pid'],signal.SIGTERM)
                row.update(stopReason=reason,stopRequestedAt=time.time());self._save_session(row)
    def closeout_ready(self,campaign):
        c=self.store.status(campaign)
        if c['state']!='closing' or c['counts']['activeTrials'] or c['counts']['reservedTrials']:return False
        if any(o['state']=='running' for o in self.store.list('operations',campaign)):return False
        reports=self.store.list('reports',campaign)
        return any(r['kind']=='final' and r['status']=='analysis' for r in reports) and all(
            any(r['kind']=='round' and r['batchId']==b['id'] and r['status']=='analysis' for r in reports)
            for b in self.store.list('batches',campaign))
    def notifications(self,id,after):
        row=self.store.get('meta_sessions',id);campaign=row['campaignId'];c=self.store.status(campaign)
        events=self.store.events(campaign,after);cursor=max([after,*[e['seq'] for e in events]])
        finished_batches={e.get('batchId') for e in events if e['type']=='batch_finished'}
        selected=[e for e in events if e['type'] in ['reference_batch_finished','reference_run_finished','reference_policy_changed','batch_finished','operation_finished','closing','resume','resource_plan_updated','resource_plan_waiting','trial_conditions_required','admission_waiting','admission_denied','limits_changed','meta_question_answered'] or
                  (e['type']=='trial_finished' and e.get('batchId') not in finished_batches)]
        finish=self.closeout_ready(campaign)
        if native_config(c):
            if after!=row.get('cursor',0):raise Refused('Notification cursor must equal acknowledged position')
            self.service.meta_api.files.refresh(campaign)
            with self.store.connection(True) as db:
                current=self.store._get(db,'meta_sessions',id)
                current.update(state='waiting',deliveredCursor=max(cursor,current.get('deliveredCursor',0)),heartbeat=time.time());self.store._save(db,'meta_sessions',current)
        else:row.update(state='waiting',cursor=cursor,heartbeat=time.time());self._save_session(row)
        pending=any(o['state']=='running' for o in self.store.list('operations',campaign)) or bool(c['counts']['activeTrials'] or c['counts']['reservedTrials'])
        from .meta_contracts import version
        state=activity_state(self.service,campaign)
        if version(self.service,campaign)in ('meta-tools-v3','meta-tools-v4','meta-tools-v5'):
            state=self.service.meta_api.receipts.status(campaign)
            details=self.service.meta_api.receipts.snapshot(campaign,'notifications',{'after':after,'cursor':cursor},selected)
            selected=[{k:e[k] for k in ['seq','type','operationId','trialId','batchId','state'] if k in e} for e in selected]
            # Event count can also grow while offline: keep the complete event list in a file.
            selected={'total':len(selected),'file':{k:details[k] for k in ['ref','path','mediaType','bytes','sha256','completeness']}}
        return {'cursor':cursor,'events':selected,'status':state,'finish':finish,
            'continue':c['config'].get('stopPolicy')=='stop-review-v1' and c['state'] in ['running','closing'] and not pending and not finish}
    def acknowledge(self,id,cursor):
        with self.store.connection(True) as db:
            row=self.store._get(db,'meta_sessions',id)
            if row.get('runtimeVersion')!='meta-runtime-v2' or row['state'] not in ['starting','running','waiting']:raise Refused('Active native Meta consumer required')
            if type(cursor) is not int or not row.get('cursor',0)<=cursor<=row.get('deliveredCursor',row.get('cursor',0)):raise Refused('Acknowledgment outside delivered range')
            row['cursor']=cursor;row['acknowledgedAt']=time.time();self.store._save(db,'meta_sessions',row)
            return {'cursor':cursor}
    def tick(self,campaign):
        c=self.store.status(campaign);sessions=self.store.list('meta_sessions',campaign);active=False
        for row in sessions:
            if row['state'] not in ['starting','running','waiting']:continue
            process=self.children.get(row['id'])
            alive=process.poll() is None if process else self.service._process_alive(row.get('pid'),row['output'])
            if alive:
                active=True
                try:
                    live=json.loads((Path(row['output'])/'summary.json').read_text()).get('status')
                    if live in ['running','waiting'] and row['state']!=live:
                        row['state']=live;self._save_session(row)
                except (OSError,ValueError):pass
                if row.get('stopRequestedAt') and time.time()-row['stopRequestedAt']>10:
                    os.kill(row['pid'],signal.SIGKILL)
                continue
            file=Path(row['output'])/'summary.json'
            summary=json.loads(file.read_text()) if file.exists() else {'status':'error','error':'Meta process lost before summary'}
            # Host audit settles calls that could not reach the ledger during a control restart.
            audits=[Path(row['output'])/'gateway-audit.jsonl',*Path(row['output']).glob('review-sessions/*/gateway-audit.jsonl')]
            for audit in [a for a in audits if a.exists()]:
                for line in read_log(audit).decode('utf-8').splitlines():
                    try:item=json.loads(line)
                    except json.JSONDecodeError:continue
                    if item.get('type')=='settled':
                        try:self.store.settle(campaign,row['leaseId'],item['id'],(item.get('usage') or {}).get('totalTokens'),not item.get('finish') or item.get('finish',{}).get('kind')=='error' or not item.get('usage'),host_audit=True)
                        except (KeyError,ValueError):pass
            for review in self.store.list('stop_reviews',campaign):
                if review['sessionId']==row['id'] and review['state']=='pending':
                    review.update(state='failed',failure='Owner session ended before review completion',finishedAt=time.time());self.store.put('stop_reviews',review)
            self.store.mark_unknown(row['leaseId'])
            row.update(state='completed' if summary['status']=='completed' else 'interrupted' if row.get('stopReason') in ('pause','reference_policy_changed') else 'failed',
                finishedAt=time.time(),summary=summary);self._save_session(row)
            if row['state']=='failed':
                if native_config(c):
                    decision=recovery(summary,0 if summary.get('turns',0)>0 else row.get('recoveryAttempt',0),time.time(),c['deadline'],stopped=bool(row.get('stopReason')))
                    row.update(state=decision['state'],recovery=decision);self._save_session(row)
                    with self.store.connection(True) as db:self.store._event(db,campaign,'meta_recovery',sessionId=row['id'],**decision)
                else:self.store.close_admission(campaign,'meta_session_failed')
            if row['state']=='completed':
                self.store.finalize(campaign)
                if native_config(c):return
                # Preserve Meta's analysis, refresh system facts after all provider settlements.
                latest={}
                for report in self.store.list('reports',campaign):
                    if report['status']=='analysis':latest[report['batchId']]=report
                for batch,report in latest.items():self.service.reports.save(campaign,report['analysis'],batch,author='meta')
                return
        c=self.store.status(campaign)
        if active or c['state'] in ['draft','paused','finished','failed']:return
        if native_config(c):
            # Committed closeout artifacts do not require one more model response.
            # Keep the session failure and its accounting; only finish the activity.
            if self.closeout_ready(campaign):
                self.store.finalize(campaign)
                return
            latest=self.store.list('meta_sessions',campaign)
            last=latest[-1] if latest else None
            if time.time()<c['deadline'] and last:
                if last['state']=='needs_attention':return
                if last['state']=='recovering':
                    if time.time()>=last['recovery']['retryAt']:self.start(campaign)
                    return
        failed=[s for s in self.store.list('meta_sessions',campaign) if s['state']=='failed']
        if time.time()>=c['deadline'] or failed:
            if not c['counts']['activeTrials']:
                self.store.finalize(campaign,c['stopReason'] or 'time_limit')
                self.service.reports.status_summary(campaign,'Meta 会话未完成完整分析；已保留所有事实、用量与停止原因。')
            return
        batches=self.store.list('batches',campaign)
        if any(b['state']=='finished' for b in batches) or (planning.enabled(c['config']) and not batches):self.start(campaign)
