"""Persisted Meta sessions and event delivery. No scientific improvement procedure is prescribed."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from .store import identity,Refused
from .meta_context import system_prompt,startup_context,activity_state
from .processes import reap_children
from .meta_composition import verify as verify_meta
from src.execution.host.models import campaign_route
from . import resource_planning as planning

class MetaDriver:
    def __init__(self,service):self.service=service;self.store=service.store;self.children={}
    def _save_session(self,row):
        # Runtime agent receipts have a separate writer; heartbeat/state updates must not erase them.
        with self.store.connection(True) as db:
            current=self.store._get(db,'meta_sessions',row['id'])
            current.update({k:v for k,v in row.items() if k not in ['agents','revision']})
            return self.store._save(db,'meta_sessions',current)
    def reap_children(self):
        reap_children(self.children,self.store,'meta_sessions',{'completed','failed','interrupted'})
    def start(self,campaign):
        c=self.store.status(campaign);now=time.time()
        if now>=c['deadline'] or c['state'] not in ['running','closing']:return
        previous=self.store.list('meta_sessions',campaign)
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
        route=campaign_route(c['config'],'meta')
        config={'id':id,'campaignId':campaign,'leaseId':lease['id'],'model':{**c['config']['meta'],'maxTokens':route['models'][0].get('maxTokens',8192)},
            'providerConfig':route,
            'deadline':c['deadline'],'softTokenLimit':c['config']['softTokenLimit'],'cursor':cursor,
            'knowledgePackId':pack.manifest['id'],'systemPrompt':system,'prompt':json.dumps(prompt,ensure_ascii=False,separators=(',',':'))}
        if frozen:config.update(metaCompositionRoot=str(frozen),metaCompositionId=composition['id'])
        file=logs/'context.json';file.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
        row=self.store.put('meta_sessions',{'id':id,'campaignId':campaign,'leaseId':lease['id'],'state':'starting','output':str(logs),
            'startedAt':now,'deadline':c['deadline'],'cursor':cursor,'knowledgePackId':config['knowledgePackId'],
            'compositionId':c['config'].get('metaComposition',{}).get('id'),'promptVersion':system['version'],'systemPromptSha256':system['sha256']})
        env=dict(self.service.providers.environment(c['config']['meta']['provider'],route),PHYEXP_CONTROL_URL=self.service.base_url,PHYEXP_META_TOKEN=token)
        with (logs/'worker.log').open('w') as log:
            process=subprocess.Popen(['node',str((frozen or self.service.source)/'src/control/meta_worker.mjs'),str(file)],
                env=env,cwd=self.service.source,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        self.children[id]=process;row.update(state='running',pid=process.pid);self._save_session(row)
        with self.store.connection(True) as db:self.store._event(db,campaign,'meta_started',sessionId=id,resumed=bool(previous))
    def interrupt(self,campaign,reason):
        for row in self.store.list('meta_sessions',campaign):
            if row['state'] in ['starting','running','waiting'] and not row.get('stopRequestedAt'):
                if self.service._process_alive(row.get('pid'),row['output']):os.kill(row['pid'],signal.SIGTERM)
                row.update(stopReason=reason,stopRequestedAt=time.time());self._save_session(row)
    def notifications(self,id,after):
        row=self.store.get('meta_sessions',id);campaign=row['campaignId'];c=self.store.status(campaign)
        events=self.store.events(campaign,after);cursor=max([after,*[e['seq'] for e in events]])
        finished_batches={e.get('batchId') for e in events if e['type']=='batch_finished'}
        selected=[e for e in events if e['type'] in ['batch_finished','operation_finished','closing','resume','resource_plan_updated','resource_plan_waiting','trial_conditions_required','admission_waiting','admission_denied','limits_changed'] or
                  (e['type']=='trial_finished' and e.get('batchId') not in finished_batches)]
        reports=self.store.list('reports',campaign);batches=self.store.list('batches',campaign)
        report_complete=any(r['kind']=='final' and r['status']=='analysis' for r in reports) and all(
            any(r['batchId']==b['id'] and r['status']=='analysis' for r in reports) for b in batches)
        finish=c['state']=='closing' and not c['counts']['activeTrials'] and not c['counts']['reservedTrials'] and report_complete
        row.update(state='waiting',cursor=cursor,heartbeat=time.time());self._save_session(row)
        pending=any(o['state']=='running' for o in self.store.list('operations',campaign)) or bool(c['counts']['activeTrials'] or c['counts']['reservedTrials'])
        return {'cursor':cursor,'events':selected,'status':activity_state(self.service,campaign),'finish':finish,
            'continue':c['config'].get('stopPolicy')=='stop-review-v1' and c['state'] in ['running','closing'] and not pending and not finish}
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
                for line in audit.read_text().splitlines():
                    try:item=json.loads(line)
                    except json.JSONDecodeError:continue
                    if item.get('type')=='settled':
                        try:self.store.settle(campaign,row['leaseId'],item['id'],(item.get('usage') or {}).get('totalTokens'),not item.get('finish') or item.get('finish',{}).get('kind')=='error' or not item.get('usage'),host_audit=True)
                        except (KeyError,ValueError):pass
            for review in self.store.list('stop_reviews',campaign):
                if review['sessionId']==row['id'] and review['state']=='pending':
                    review.update(state='failed',failure='Owner session ended before review completion',finishedAt=time.time());self.store.put('stop_reviews',review)
            self.store.mark_unknown(row['leaseId'])
            row.update(state='completed' if summary['status']=='completed' else 'interrupted' if row.get('stopReason')=='pause' else 'failed',
                finishedAt=time.time(),summary=summary);self._save_session(row)
            if row['state']=='failed':self.store.close_admission(campaign,'meta_session_failed')
            if row['state']=='completed':
                self.store.finalize(campaign)
                # Preserve Meta's analysis, refresh system facts after all provider settlements.
                latest={}
                for report in self.store.list('reports',campaign):
                    if report['status']=='analysis':latest[report['batchId']]=report
                for batch,report in latest.items():self.service.reports.save(campaign,report['analysis'],batch,author='meta')
                return
        c=self.store.status(campaign)
        if active or c['state'] in ['draft','paused','finished','failed']:return
        failed=[s for s in self.store.list('meta_sessions',campaign) if s['state']=='failed']
        if time.time()>=c['deadline'] or failed:
            if not c['counts']['activeTrials']:
                self.store.finalize(campaign,c['stopReason'] or 'time_limit')
                self.service.reports.status_summary(campaign,'Meta 会话未完成完整分析；已保留所有事实、用量与停止原因。')
            return
        batches=self.store.list('batches',campaign)
        if any(b['state']=='finished' for b in batches) or (planning.enabled(c['config']) and not batches):self.start(campaign)
