"""Persisted Meta sessions and event delivery. No scientific improvement procedure is prescribed."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from .store import identity,Refused
from .meta_context import system_prompt,startup_context,activity_state
from src.execution.host.network import provider_environment

class MetaDriver:
    def __init__(self,service):self.service=service;self.store=service.store;self.children={}
    def start(self,campaign):
        c=self.store.status(campaign);now=time.time()
        if now>=c['deadline'] or c['state'] not in ['running','closing']:return
        previous=self.store.list('meta_sessions',campaign)
        prompt=startup_context(self.service,campaign)
        system=system_prompt(c['config'])
        pack=self.service.knowledge_for(campaign)
        lease,token=self.service.lease(campaign,'meta',c['deadline'])
        id=identity('meta');logs=self.service.data/'campaigns'/campaign/'meta-sessions'/id;logs.mkdir(parents=True)
        cursor=self.store.last_event(campaign)
        config={'id':id,'campaignId':campaign,'leaseId':lease['id'],'model':{**c['config']['meta'],'maxTokens':8192},
            'deadline':c['deadline'],'softTokenLimit':c['config']['softTokenLimit'],'cursor':cursor,
            'knowledgePackId':pack.manifest['id'],'systemPrompt':system,'prompt':json.dumps(prompt,ensure_ascii=False,separators=(',',':'))}
        file=logs/'context.json';file.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
        row=self.store.put('meta_sessions',{'id':id,'campaignId':campaign,'leaseId':lease['id'],'state':'starting','output':str(logs),
            'startedAt':now,'deadline':c['deadline'],'cursor':cursor,'knowledgePackId':config['knowledgePackId'],
            'promptVersion':system['version'],'systemPromptSha256':system['sha256']})
        env=dict(provider_environment(),PHYEXP_CONTROL_URL=self.service.base_url,PHYEXP_META_TOKEN=token)
        with (logs/'worker.log').open('w') as log:
            process=subprocess.Popen(['node',str(self.service.source/'src/control/meta_worker.mjs'),str(file)],
                env=env,cwd=self.service.source,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        self.children[id]=process;row.update(state='running',pid=process.pid);self.store.put('meta_sessions',row)
        with self.store.connection(True) as db:self.store._event(db,campaign,'meta_started',sessionId=id,resumed=bool(previous))
    def interrupt(self,campaign,reason):
        for row in self.store.list('meta_sessions',campaign):
            if row['state'] in ['starting','running','waiting'] and not row.get('stopRequestedAt'):
                if self.service._process_alive(row.get('pid'),row['output']):os.kill(row['pid'],signal.SIGTERM)
                row.update(stopReason=reason,stopRequestedAt=time.time());self.store.put('meta_sessions',row)
    def notifications(self,id,after):
        row=self.store.get('meta_sessions',id);campaign=row['campaignId'];c=self.store.status(campaign)
        events=self.store.events(campaign,after);cursor=max([after,*[e['seq'] for e in events]])
        selected=[e for e in events if e['type'] in ['batch_finished','operation_finished','closing','resume']]
        reports=self.store.list('reports',campaign);batches=self.store.list('batches',campaign)
        report_complete=any(r['kind']=='final' and r['status']=='analysis' for r in reports) and all(
            any(r['batchId']==b['id'] and r['status']=='analysis' for r in reports) for b in batches)
        finish=c['state']=='closing' and not c['counts']['activeTrials'] and not c['counts']['reservedTrials'] and report_complete
        row.update(state='waiting',cursor=cursor,heartbeat=time.time());self.store.put('meta_sessions',row)
        return {'cursor':cursor,'events':selected,'status':activity_state(self.service,campaign),'finish':finish}
    def tick(self,campaign):
        c=self.store.status(campaign);sessions=self.store.list('meta_sessions',campaign);active=False
        for row in sessions:
            if row['state'] not in ['starting','running','waiting']:continue
            process=self.children.get(row['id'])
            alive=process.poll() is None if process else self.service._process_alive(row.get('pid'),row['output'])
            if alive:
                active=True
                if row.get('stopRequestedAt') and time.time()-row['stopRequestedAt']>10:
                    os.kill(row['pid'],signal.SIGKILL)
                continue
            file=Path(row['output'])/'summary.json'
            summary=json.loads(file.read_text()) if file.exists() else {'status':'error','error':'Meta process lost before summary'}
            # Host audit settles calls that could not reach the ledger during a control restart.
            audit=Path(row['output'])/'gateway-audit.jsonl'
            if audit.exists():
                for line in audit.read_text().splitlines():
                    try:item=json.loads(line)
                    except json.JSONDecodeError:continue
                    if item.get('type')=='settled':
                        try:self.store.settle(campaign,row['leaseId'],item['id'],(item.get('usage') or {}).get('totalTokens'),not item.get('finish') or item.get('finish',{}).get('kind')=='error' or not item.get('usage'),host_audit=True)
                        except (KeyError,ValueError):pass
            self.store.mark_unknown(row['leaseId'])
            row.update(state='completed' if summary['status']=='completed' else 'interrupted' if row.get('stopReason')=='pause' else 'failed',
                finishedAt=time.time(),summary=summary);self.store.put('meta_sessions',row)
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
        if any(b['state']=='finished' for b in batches):self.start(campaign)
