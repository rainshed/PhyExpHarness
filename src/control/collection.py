"""Durable process workers for verified results and complete evidence indexing.

No model execution. The database row is the queue; a per-job flock is the
execution lease. A controller restart discovers surviving workers by identity.
"""
import fcntl
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .store import Store


class Collections:
    def __init__(self, service):
        self.service=service;self.store=service.store;self.children={}

    def enqueue(self, trial):
        key='collection-'+hashlib.sha256((trial['id']+trial['launchId']).encode()).hexdigest()
        directory=self.service.data/'campaigns'/trial['campaignId']/'collections'
        directory.mkdir(parents=True,exist_ok=True)
        finished=None
        try:
            receipt=json.loads((Path(trial['output'])/'supervisor.json').read_text())
            if receipt.get('state')=='finished':finished=datetime.fromisoformat(receipt['finishedAt']).timestamp()
        except (OSError,ValueError,KeyError,TypeError):pass
        with self.store.connection(True) as db:
            existing=db.execute('SELECT data FROM collection_jobs WHERE id=?',(key,)).fetchone()
            if existing:return json.loads(existing['data'])
            current=self.store._get(db,self.store.run_table(trial['id']),trial['id'])
            if current['state'] not in ('running','launching'):return
            current.update(state='collecting',phase='collection',output=trial['output'],executionFinishedAt=finished,executionFinishObservedAt=time.time())
            self.store._save_run(db,current)
            return self.store._save(db,'collection_jobs',{'id':key,'campaignId':trial['campaignId'],
                'trialId':trial['id'],'state':'queued','stage':'verify','attempts':0,'createdAt':time.time(),
                'lockPath':str(directory/(key+'.lock'))})

    def pid(self,job):
        child=self.children.get(job['id'])
        if job['state'] in ('complete','failed') and not(child and child.poll() is None):return None
        # The lease owner writes its identity before doing any work. This also
        # closes the controller-crash window between spawn and PID registration.
        try:owner=json.loads(Path(job['lockPath']).read_text()).get('pid')
        except (OSError,ValueError,KeyError):owner=None
        if owner and self.service._process_alive(owner,job['lockPath']):return owner
        if child and child.poll() is None:return child.pid
        if job.get('pid') and job.get('lockPath') and self.service._process_alive(job['pid'],job['lockPath']):return job['pid']
        return None

    def alive(self,job):return self.pid(job) is not None

    def tick(self):
        jobs=self.store.list('collection_jobs');active={'verify':0,'index':0,'report':0}
        for job in jobs:
            if self.alive(job):active[job.get('workerStage',job.get('stage','verify'))]+=1;continue
            child=self.children.pop(job['id'],None)
            if child:child.poll()
        for job in jobs:
            stage=job.get('stage','verify')
            if active[stage]>=(2 if stage=='verify' else 1):continue
            if job['state'] not in ('queued','running','retry') or self.alive(job):continue
            if self.store.deletion(job['campaignId']):continue
            if job.get('retryAt',0)>time.time():continue
            if job['attempts']>=3:
                self.fail(job,'Collection worker repeatedly exited before completion');continue
            # flock prevents two controllers/restarted children executing a job.
            with self.store.connection(True) as db:
                current=self.store._get(db,'collection_jobs',job['id'])
                if current['revision']!=job['revision']:continue
                job=self.store._save(db,'collection_jobs',{**current,'state':'running',
                    'attempts':current['attempts']+1,'workerStage':stage,'startedAt':time.time()})
            log=Path(job['lockPath']).with_suffix('.log')
            with log.open('a') as stream:
                child=subprocess.Popen([sys.executable,'-m','src.control.collection',str(self.service.data),
                    str(self.service.source),job['id'],job['lockPath']],cwd=self.service.source,
                    stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            self.children[job['id']]=child
            active[stage]+=1

    def fail(self, job, error):
        with self.store.connection(True) as db:
            current=self.store._get(db,'collection_jobs',job['id'])
            self.store._save(db,'collection_jobs',{**current,'state':'failed','error':error,'finishedAt':time.time()})
        if job.get('kind')=='report-summary':return
        trial=self.store.run(job['trialId'])
        if trial['state']=='collecting':
            self.store.trial_update(trial['id'],state='failed',finishedAt=trial.get('executionFinishedAt') or time.time(),
                failure={'code':'result_collection_failed','stage':'collection','source':'controller'},
                lastCollectionError=error,scoringStatus='failed')
        else:self.store.trial_update(trial['id'],evidenceIndex={'state':'failed','error':error,'completed':job.get('completed',0)})

    def stop(self, campaign):
        alive=False
        for job in self.store.list('collection_jobs',campaign):
            pid=self.pid(job)
            if pid:
                try:os.kill(pid,signal.SIGTERM)
                except ProcessLookupError:pass
                alive=True
        return not alive


def work(data, source, id, lockpath):
    # Only trusted collection code is constructed, never a second control service
    # (which would recover builds/start other runtime components).
    from .service import ControlService
    from src.evidence.library import EvidenceLibrary
    service=ControlService.__new__(ControlService)
    service.data=Path(data);service.source=Path(source);service.store=Store(Path(data)/'control.sqlite')
    service.evidence=EvidenceLibrary(service.store,data)
    store=service.store
    with Path(lockpath).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        lock.seek(0);lock.truncate();json.dump({'pid':os.getpid()},lock);lock.flush();os.fsync(lock.fileno())
        job=store.get('collection_jobs',id)
        if job['state'] in ('complete','failed') or store.deletion(job['campaignId']):return
        try:
            with store.connection(True) as db:
                job=store._save(db,'collection_jobs',{**store._get(db,'collection_jobs',id),'pid':os.getpid()})
            if job.get('kind')=='report-summary':
                from src.reporting.reports import Reports
                Reports(store,data).status_summary(job['campaignId'],job['reason'],meta_request={'requestId':job['id'],'payload':job['reason']})
                with store.connection(True) as db:
                    current=store._get(db,'collection_jobs',id)
                    store._save(db,'collection_jobs',{**current,'state':'complete','finishedAt':time.time()})
                return
            trial=store.run(job['trialId'])
            if job.get('stage','verify')=='verify':
                if trial['state']=='collecting':trial=service._collect(trial,defer_evidence=True)
                with store.connection(True) as db:
                    current=store._get(db,'collection_jobs',id)
                    store._save(db,'collection_jobs',{**current,'state':'queued','stage':'index','attempts':0,'retryAt':0})
                return
            summary=trial['summary']
            def progress(cursor,count,total):
                with store.connection(True) as db:
                    current=store._get(db,'collection_jobs',id)
                    store._save(db,'collection_jobs',{**current,'cursor':cursor,'completed':count,'total':total,'heartbeat':time.time()})
                store.trial_update(trial['id'],evidenceIndex={'state':'running','completed':count,'total':total})
            service.evidence.ingest_complete(trial,summary,after=job.get('cursor'),progress=progress,retain_items=False)
            store.trial_update(trial['id'],evidenceIndex={'state':'complete','completedAt':time.time()},evidenceIndexedAt=time.time())
            with store.connection(True) as db:
                current=store._get(db,'collection_jobs',id)
                store._save(db,'collection_jobs',{**current,'state':'complete','finishedAt':time.time()})
                store._event(db,job['campaignId'],'evidence_indexed',trialId=trial['id'])
        except Exception as error:
            if store.deletion(job['campaignId']):return
            with store.connection(True) as db:
                current=store._get(db,'collection_jobs',id)
                store._save(db,'collection_jobs',{**current,'state':'retry','error':str(error)[:1000],'retryAt':time.time()+5})
            raise


if __name__=='__main__':work(*sys.argv[1:])
