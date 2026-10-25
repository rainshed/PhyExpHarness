"""Durable user-authorized Campaign deletion, independent of UI lifetime."""
import contextlib
import fcntl
import hashlib
import json
import os
import threading
import time

from .store import TABLES, Conflict, Refused, encoded
from .deletion_storage import Inventory, remove_path, rewrite, safe_path
from .deletion_runtime import stop_processes, cleanup_resources, ensure_unused


class ActivityAccess:
    """Drain only the activity being removed, including streamed responses."""
    def __init__(self):
        self.lock=threading.Lock();self.scopes={};self.cleaning=set()

    @property
    def readers(self):return sum(self.scopes.values())

    @contextlib.contextmanager
    def enter(self,campaign=None):
        with self.lock:
            if campaign in self.cleaning or campaign is None and self.cleaning:
                raise Conflict('此活动正在完成清理，请稍后重试。')
            self.scopes[campaign]=self.scopes.get(campaign,0)+1
        try:yield
        finally:
            with self.lock:self.scopes[campaign]-=1

    @contextlib.contextmanager
    def exclusive(self,campaign=None):
        with self.lock:
            acquired=not self.cleaning and not self.scopes.get(None,0) and not self.scopes.get(campaign,0)
            if campaign is None:acquired=acquired and not self.readers
            if acquired:self.cleaning.add(campaign)
        try:yield acquired
        finally:
            if acquired:
                with self.lock:self.cleaning.remove(campaign)


class Deletions:
    def __init__(self, service):
        self.service, self.store = service, service.store
        self.worker = None
        self.lock = threading.Lock()

    def save(self, job):
        with self.store.connection(True) as db:
            db.execute('INSERT OR REPLACE INTO deletions VALUES(?,?)',(job['campaignId'],encoded(job)))

    @staticmethod
    def public(job):
        return {k:job[k] for k in ('campaignId','state','phase','error','requestedAt','completedAt','counts','sharedRetained') if k in job}

    def preview(self, campaign):
        with self.store.connection() as db:
            job = self.store.deletion(campaign,db)
            if job:return self.public(job)
            c = self.store._get(db,'campaigns',campaign)
            plan = Inventory(self.service,campaign,db).build()
            return {'campaignId':campaign,'state':'preview','expectedRevision':c['revision'],
                    'name':c['config'].get('name') or campaign,'counts':plan['counts'],
                    'sharedRetained':plan['sharedRetained'],'blockers':plan['blockers'],
                    'requiresStop':c['state'] not in ('draft','finished','failed') or
                        any(o['state'] in ('pending','running') for o in self.store._list(db,'operations',campaign))}

    def request(self, campaign, expectedRevision, idempotencyKey, retry=False):
        if not isinstance(idempotencyKey,str) or not 1 <= len(idempotencyKey) <= 200:
            raise Refused('Idempotency key required')
        if type(retry) is not bool:raise Refused('Invalid retry flag')
        key = hashlib.sha256(idempotencyKey.encode()).hexdigest()
        # Scheduling/launch and deletion acceptance share the same admission window.
        with self.service.tick_lock, self.store.connection(True) as db:
            job = self.store.deletion(campaign,db)
            if job:
                if job['state'] == 'failed' and retry and key not in job.get('keys',[]):
                    job.update(state='running',error=None)
                    job.setdefault('keys',[]).append(key)
                    job.pop('stopStartedAt',None)
                    db.execute('UPDATE deletions SET data=? WHERE campaign=?',(encoded(job),campaign))
                return self.public(job)
            c = self.store._get(db,'campaigns',campaign)
            if type(expectedRevision) is not int or expectedRevision != c['revision']:
                raise Conflict('活动已变化，请重新查看删除范围后确认。')
            plan = Inventory(self.service,campaign,db).build()
            if plan['blockers']:raise Conflict('；'.join(b['message'] for b in plan['blockers']))
            job = {'campaignId':campaign,'state':'running','phase':'stopping','keys':[key],
                   'requestedAt':time.time(),'counts':plan['counts'],'sharedRetained':plan['sharedRetained']}
            c.update(state='deleting',explorationClosed=True,revision=c['revision']+1)
            db.execute('UPDATE campaigns SET data=? WHERE id=?',(encoded(c),campaign))
            for lease in self.store._list(db,'leases',campaign):
                lease['revoked'] = True
                db.execute('UPDATE leases SET data=? WHERE id=?',(encoded(lease),lease['id']))
            db.execute('INSERT INTO deletions VALUES(?,?)',(campaign,encoded(job)))
            return self.public(job)

    def route_campaign(self, path):
        parts = path.strip('/').split('/')
        if len(parts) < 2:return
        kind, id = parts[:2]
        if kind == 'campaigns':
            campaign = id
        elif kind == 'meta':campaign = id
        else:
            table = {'candidates':'candidates','trials':self.store.run_table(id),'evidence':'evidence',
                     'reports':'reports','exports':'exports','meta-sessions':'meta_sessions',
                     'meta-questions':'meta_questions','accounting':'leases','model-access':'leases'}.get(kind)
            if not table:return
            try:campaign = self.store.get(table,id)['campaignId']
            except KeyError:return
        return campaign

    def guard_route(self,path):
        parts=path.strip('/').split('/')
        if parts[0]=='campaigns' and (len(parts)==2 or len(parts)>2 and parts[2] in ('deletion','events')):return
        campaign=self.route_campaign(path)
        if campaign:self.store.writable(campaign)

    def tick(self):
        with self.lock:
            if self.worker and self.worker.is_alive():return
            with self.store.connection() as db:
                jobs = [json.loads(r['data']) for r in db.execute('SELECT data FROM deletions')]
            job = next((j for j in jobs if j['state'] == 'running'),None)
            if job:
                self.worker = threading.Thread(target=self.advance,args=(job['campaignId'],),name='phyexp-delete',daemon=True)
                self.worker.start()

    def advance(self, campaign):
        job = self.store.deletion(campaign)
        if not job or job['state'] != 'running':return
        try:
            if job['phase'] == 'stopping':
                with self.service.tick_lock:
                    if not self.service.collections.stop(campaign):return
                    if not stop_processes(self.service,campaign,job,self.save):return
                # Includes already-running builds whose callbacks are now fenced.
                if any(not self.service.operations[o['id']].done() for o in self.store.list('operations',campaign) if o['id'] in self.service.operations):return
            with self.service.access.exclusive(campaign) as acquired:
                if not acquired:return
                # Coordinate explicit legacy migration/restore as well as API work.
                lockfile = safe_path(self.service.data,self.service.data/'history-storage.lock')
                with lockfile.open('a') as lock:
                    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:return
                    if not self.service.storage.maintenance_lock.acquire(blocking=False):return
                    try:self.clean(job)
                    finally:self.service.storage.maintenance_lock.release()
        except Exception as error:
            if (self.store.deletion(campaign) or {}).get('state')=='deleted':return
            job.update(state='failed',error=str(error))
            self.save(job)

    def clean(self, job):
        campaign = job['campaignId']
        # Build/inspect/clean engine resources outside SQLite's writer lock.
        if 'plan' not in job:
            with self.store.connection() as db:plan=Inventory(self.service,campaign,db).build()
            if plan['blockers']:raise Refused('；'.join(b['message'] for b in plan['blockers']))
            ensure_unused(self.service.data,plan)
            cleanup_resources(self.service,campaign,plan)
            job.update(phase='cleaning',plan=plan,counts=plan['counts'],sharedRetained=plan['sharedRetained'])
            self.save(job)
        plan=job['plan'];ensure_unused(self.service.data,plan)
        from src.evidence.objects import Objects
        from .database import begin_write
        trash=safe_path(self.service.data,self.service.data/'deletion-trash'/campaign)
        trash.mkdir(parents=True,exist_ok=True)
        # Object publication always precedes DB registration: use the same lock order.
        with contextlib.ExitStack() as locks, Objects(self.service.data).locked(), self.store.connection() as db:
            version=db.execute('PRAGMA data_version').fetchone()[0]
            inventory=Inventory(self.service,campaign,db)
            keep=inventory.retained({self.service.data/p for p in plan['paths']})
            from .deletion_storage import walk_stats
            for _,info in walk_stats(trash):
                original=inventory.artifact_inodes.get((info.st_dev,info.st_ino))
                if original:inventory.own_links[original]=inventory.own_links.get(original,0)+1
            for path in plan['paths']:
                if not (path.startswith('cache/project-builds/') and path.endswith('.lock')):continue
                target=safe_path(self.service.data,path)
                if target not in keep and target.exists():
                    stream=locks.enter_context(target.open('r'))
                    try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:raise Refused('构建缓存仍在使用，请结束构建后重试：'+str(target))
            begin_write(db)
            # A concurrent publication invalidates the inventory. Retry next tick.
            if db.execute('PRAGMA data_version').fetchone()[0]!=version:return
            for entry in plan['rewrites']:rewrite(self.service.data,entry)
            paths=sorted(plan['paths'],key=lambda p:p.startswith('artifacts/'))
            for path in paths:
                target=safe_path(self.service.data,path)
                if target in keep or not target.exists():continue
                if path.startswith('artifacts/') and target.stat().st_nlink>1:
                    # Private views are already detached; their links disappear in
                    # the purge below. Unexplained links were checked by Inventory.
                    expected=inventory.own_links.get(target,0)+1
                    if target.stat().st_nlink>expected:
                        raise Refused('共享归档仍有未登记的文件引用，请先核实：'+str(target))
                os.replace(target,trash/hashlib.sha256(path.encode()).hexdigest())
        # Recursive removal never holds a writer or publication lock. The saved
        # plan and deterministic trash names recover a crash after any rename.
        for path in trash.iterdir():remove_path(self.service.data,str(path))
        remove_path(self.service.data,str(trash))
        with self.store.connection(True) as db:
            for row in db.execute("SELECT key,result FROM commands WHERE campaign='global' AND kind='create'").fetchall():
                if json.loads(row['result']).get('id') == campaign:
                    db.execute('INSERT OR IGNORE INTO deleted_create_keys VALUES(?)',(hashlib.sha256(row['key'].encode()).hexdigest(),))
                    db.execute("DELETE FROM commands WHERE campaign='global' AND kind='create' AND key=?",(row['key'],))
            for table in TABLES:
                db.execute(f'DELETE FROM {table} WHERE campaign=?',(campaign,))
            db.execute('DELETE FROM events WHERE campaign=?',(campaign,))
            db.execute('DELETE FROM commands WHERE campaign=?',(campaign,))
            result = {'campaignId':campaign,'state':'deleted','phase':'done'}
            db.execute('UPDATE deletions SET data=? WHERE campaign=?',(encoded(result),campaign))
        # No names, config, evidence, file list or raw command keys in the tombstone.
        for id, future in list(self.service.operations.items()):
            if future.done():del self.service.operations[id]
        with self.service.storage.lock:
            self.service.storage.waiting.pop(campaign,None)
            self.service.storage.metrics['campaigns'].pop(campaign,None)
            self.service.storage.errors=[e for e in self.service.storage.errors if e.get('trialId') not in job['plan'].get('trialIds',[])]
            self.service.storage.last_scan=0
