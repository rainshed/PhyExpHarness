"""Host-owned storage maintenance and reversible capacity admission for new activities."""
import fcntl
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import Counter
from pathlib import Path
from src.evidence.objects import Objects, POLICY, atomic_json, enabled
from .store import Refused

GiB=1024**3
DEFAULTS={'version':1,'maxDataBytes':40*GiB,'maxCampaignBytes':20*GiB,'minFreeBytes':10*GiB,
    'criticalFreeBytes':2*GiB,'resumeMarginBytes':GiB,'trialReserveBytes':512*1024**2,
    'metaReserveBytes':256*1024**2,'scanSeconds':60,'garbageGraceSeconds':21600,
    'cacheAgeSeconds':86400,'additionalPaths':[]}
ACTIVE={'starting','launching','running','waiting','reserved'}


class Storage:
    def __init__(self, service):
        self.service=service;self.data=Path(service.data).resolve();self.store=service.store;self.objects=Objects(self.data)
        self.lock=threading.RLock();self.maintenance_lock=threading.Lock();self.worker=None;self.last_scan=0;self.last_maintenance=0;self.waiting={};self.samples=[]
        self.metrics={'bytes':0,'files':0,'groups':{},'campaigns':{},'observedAt':None}
        self.errors=[];self.reclaimed=0
        self.policy_file=self.data/'storage-policy.json'
        self.policy={**DEFAULTS,**(json.loads(self.policy_file.read_text()) if self.policy_file.exists() else {})}
        self.validate(self.policy)

    def validate(self,p):
        if set(p)!=set(DEFAULTS) or p['version']!=1:raise ValueError('Unknown storage policy fields/version')
        for key in DEFAULTS.keys()-{'additionalPaths','version'}:
            if type(p[key]) is not int or p[key]<=0:raise ValueError('Storage limits must be positive integers: '+key)
        if p['criticalFreeBytes']>=p['minFreeBytes']:raise ValueError('Critical free space must be below admission reserve')
        if p['scanSeconds']<5:raise ValueError('Storage scan interval must be at least 5 seconds')
        if not isinstance(p['additionalPaths'],list) or any(not isinstance(x,str) or not Path(x).is_absolute() or not Path(x).is_dir() for x in p['additionalPaths']):raise ValueError('Additional storage paths must be existing absolute directories')

    def configure(self,changes):
        with self.lock:
            p={**self.policy,**changes};self.validate(p);atomic_json(self.policy_file,p);self.policy=p
            self.last_scan=0;return self.snapshot()

    def inventory(self,force=False):
        with self.lock:
            now=time.time()
            if not force and now-self.last_scan<self.policy['scanSeconds']:return
            groups=Counter();seen=set();files=0;owned={};campaign_sets={}
            for c in self.store.list('campaigns'):
                cid=c['id'];owned[self.data/'campaigns'/cid]=cid
                for t in self.store.runs(cid):
                    if t.get('output'):
                        p=Path(t['output']).resolve()
                        if p.is_relative_to(self.data):owned[p]=cid
                campaign_sets[cid]={}
            for directory,dirs,names in os.walk(self.data,followlinks=False):
                dirs[:]=[d for d in dirs if not Path(directory,d).is_symlink()]
                base=Path(directory);rel=base.relative_to(self.data)
                owner=next((owned[p] for p in (base,*base.parents) if p in owned),None)
                for name in names:
                    p=base/name
                    try:s=p.lstat()
                    except FileNotFoundError:continue
                    if p.is_symlink():continue
                    files+=1;key=(s.st_dev,s.st_ino);size=s.st_blocks*512
                    if key not in seen:groups[rel.parts[0] if rel.parts else 'database-and-state']+=size;seen.add(key)
                    if owner:campaign_sets[owner][key]=size
            # Bodies can precede their readable views; charge them to the owning activity too.
            for c in campaign_sets:
                for row in self.store.list('evidence',c):
                    try:s=Path(row['path']).stat();campaign_sets[c][(s.st_dev,s.st_ino)]=s.st_blocks*512
                    except (FileNotFoundError,KeyError):continue
            size=sum(groups.values());self.samples.append((now,size));self.samples=[x for x in self.samples if now-x[0]<=86400][-1441:]
            growth=None
            if len(self.samples)>1 and now-self.samples[0][0]>=3600:
                growth=max(0,(size-self.samples[0][1])/(now-self.samples[0][0]))
            self.metrics={'bytes':size,'files':files,'groups':dict(groups),'campaigns':{c:sum(v.values()) for c,v in campaign_sets.items()},'observedAt':now,'growthBytesPerSecond':growth}
            self.last_scan=now

    def disks(self):
        values=[];seen=set()
        for index,p in enumerate([str(self.data),*self.policy['additionalPaths']]):
            try:
                device=Path(p).stat().st_dev
                if device in seen:continue
                seen.add(device);usage=shutil.disk_usage(p);nodes=os.statvfs(p)
                values.append({'label':'data' if index==0 else 'container-or-extra-'+str(index),'total':usage.total,'free':usage.free,'freeInodes':nodes.f_favail})
            except OSError:values.append({'label':'unavailable','free':0,'total':0,'freeInodes':0})
        return values

    def pressure(self,campaign=None,extra=0):
        self.inventory();p=self.policy;disks=self.disks();active=0;metas=0
        for c in self.store.list('campaigns'):
            active+=sum(t['state'] in ('launching','running') for t in self.store.runs(c['id']))
            metas+=sum(s.get('state') in ('starting','running','waiting') for s in self.store.list('meta_sessions',c['id']))
        reserve=active*p['trialReserveBytes']+metas*p['metaReserveBytes']+extra
        margin=p['resumeMarginBytes'] if self.waiting.get(campaign,False) else 0
        reasons=[]
        if any(d['free']<=p['minFreeBytes']+reserve+margin for d in disks):reasons.append('磁盘剩余空间不足，需保留在途任务收尾容量')
        if any(d['freeInodes']<10000 for d in disks):reasons.append('文件系统可用文件数量不足')
        if self.metrics['bytes']+reserve+margin>=p['maxDataBytes']:reasons.append('活动数据达到全局存储预算')
        used=self.metrics['campaigns'].get(campaign,0)
        if campaign and used+extra+margin>=p['maxCampaignBytes']:reasons.append('本活动达到存储预算')
        return {'waiting':bool(reasons),'reasons':reasons,'reservedBytes':reserve,'disks':disks,'critical':any(d['free']<p['criticalFreeBytes'] for d in disks),'campaignBytes':used}

    def permit(self,campaign,kind='request'):
        if not enabled(self.store.get('campaigns',campaign)['config']):return True
        with self.lock:
            extra=self.policy['trialReserveBytes'] if kind=='trial' else self.policy['metaReserveBytes'] if kind in ('meta','build') else 0
            result=self.pressure(campaign,extra);waiting=result['waiting'];old=self.waiting.get(campaign)
            self.waiting[campaign]=waiting
            if old!=waiting:
                with self.store.connection(True) as db:self.store._event(db,campaign,'storage_waiting' if waiting else 'storage_ready',reasons=result['reasons'])
            return not waiting

    def view(self,campaign):
        with self.lock:
            value=self.pressure(campaign);growth=self.metrics.get('growthBytesPerSecond')
            available=max(0,min(self.policy['maxDataBytes']-self.metrics['bytes'],self.policy['maxCampaignBytes']-value['campaignBytes'],*[d['free']-self.policy['minFreeBytes']-value['reservedBytes'] for d in value['disks']]))
            return {**value,'policy':POLICY,'dataBytes':self.metrics['bytes'],'maxDataBytes':self.policy['maxDataBytes'],'maxCampaignBytes':self.policy['maxCampaignBytes'],
                'fileCount':self.metrics['files'],'groups':self.metrics['groups'],'observedAt':self.metrics['observedAt'],'reclaimedBytes':self.reclaimed,
                'growthBytesPerSecond':growth,'estimatedSecondsRemaining':available/growth if growth and growth>0 else None,'errors':self.errors[-5:]}

    def snapshot(self):return {'policy':self.policy,'usage':self.view(None)}

    def schedule(self):
        if time.time()-self.last_maintenance<self.policy['scanSeconds'] or self.worker and self.worker.is_alive():return
        def run():
            try:self.maintain()
            except Exception as error:self.errors.append({'operation':'maintenance','error':str(error)[:250]})
        self.worker=threading.Thread(target=run,name='phyexp-storage',daemon=True);self.worker.start()

    def maintain(self,force=False):
        from .store import Conflict
        try:
            with self.service.access.enter():self._maintain(force)
        except Conflict:
            if not self.service.access.cleaning:raise

    def _maintain(self,force=False):
        with self.maintenance_lock:
            now=time.time()
            if not force and now-self.last_maintenance<self.policy['scanSeconds']:return
            self.last_maintenance=now
            try:listing=subprocess.check_output(['ps','-Ao','command='],text=True,timeout=10)
            except (OSError,subprocess.SubprocessError):listing=None
            campaigns=[c for c in self.store.list('campaigns') if enabled(c['config']) and c['state']!='deleting']
            for c in campaigns:
                cid=c['id']
                for row in self.store.runs(cid):
                    if row['state'] not in ('finished','failed','cancelled','unknown') or not row.get('output'):continue
                    directory=Path(row['output']).resolve()
                    if not directory.is_relative_to(self.data) or not directory.is_dir() or (directory/'artifact-archive.json').exists():continue
                    if listing is None or str(directory) in listing or self.service._process_alive(row.get('pid'),directory):continue
                    try:self.objects.archive(directory)
                    except (OSError,ValueError) as error:self.errors.append({'operation':'archive','trialId':row['id'],'error':str(error)[:250]})
            protected={r['sha256'] for r in self.store.list('evidence')}
            protected.update(r['sha256'] for r in self.store.list('source_adoptions'))
            for file in (self.data/'trials').glob('*/artifact-archive.json'):
                try:protected.update(v['sha256'] for v in json.loads(file.read_text())['files'].values())
                except (OSError,ValueError,KeyError):return  # Unknown reachability: collect nothing.
            self.reclaimed+=self.objects.prune(protected,now-self.policy['garbageGraceSeconds'])
            # Only old noncurrent generations. Active jobs and unknown process state protect caches.
            active=any(t['state'] in ACTIVE for c in self.store.list('campaigns') for t in self.store.runs(c['id'])) or any(s.get('state') in ACTIVE for s in self.store.list('meta_sessions')) or any(o.get('state')=='running' for o in self.store.list('operations'))
            if not active and listing is not None:self.prune_caches(listing,now)
            self.errors=self.errors[-20:];self.inventory(force=True)

    def prune_caches(self,listing,now):
        for family in ('adapters','dependencies'):
            parent=self.data/'cache'/family
            if not parent.exists():continue
            for directory in parent.iterdir():
                match=re.fullmatch('([a-f0-9]{64})-[a-f0-9]{32}',directory.name)
                if not match or directory.is_symlink() or not directory.is_dir() or now-directory.stat().st_mtime<self.policy['cacheAgeSeconds']:continue
                key=match[1]
                with (parent/(key+'.lock')).open('a') as lock:
                    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:continue
                    try:current=json.loads((parent/(key+'.json')).read_text())['generation']
                    except (OSError,ValueError,KeyError):continue
                    if current==directory.name or str(directory) in listing:continue
                    linked=False
                    for base,dirs,files in os.walk(self.data,followlinks=False):
                        for name in dirs+files:
                            path=Path(base,name)
                            if path.is_symlink() and path.resolve().is_relative_to(directory):linked=True;break
                        if linked:break
                    if linked:continue
                    shutil.rmtree(directory)
