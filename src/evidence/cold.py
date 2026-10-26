"""Verified NFS copies with a local locator database and conservative cache eviction.

Only closed Trial files are eligible. Network I/O runs in the archive worker;
readers restore on demand. Published views of an unfinished Campaign pin bytes.
Neither experiment identities nor evidence hashes/paths are rewritten.
"""
import contextlib
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid

from .objects import atomic_json

ACTIVE = {'running','starting','waiting','launching','collecting','reserved'}
TERMINAL = {'finished','failed','cancelled','unknown'}


class ColdArchive:
    def __init__(self, data):
        self.data = Path(data).absolute()
        self.policy_file = self.data/'archive-policy.json'
        self.policy = json.loads(self.policy_file.read_text()) if self.policy_file.exists() else None
        self.index = self.data/'archive-index.sqlite'
        self.state = self.data/'archive-state.json'

    def configured(self):
        return bool(self.policy and self.policy.get('enabled'))

    def validate(self):
        p=self.policy
        self.root()
        if type(p.get('enabled')) is not bool or type(p.get('evict',False)) is not bool:raise ValueError('Invalid archive switches')
        fields={'bytesPerSecond','maxBytes','minFreeBytes','localReserveBytes','cacheSeconds','minObjectBytes','lockTimeoutSeconds','restoreTimeoutSeconds'}
        if set(p)-fields-{'version','enabled','evict','root','instance'}:raise ValueError('Unknown archive policy fields')
        for key in fields & p.keys():
            if type(p[key]) is not int or p[key] < (0 if key=='bytesPerSecond' else 1):raise ValueError('Invalid archive limit: '+key)

    def root(self):
        p = self.policy
        if not p or p.get('version') != 1 or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',p.get('instance','')):
            raise ValueError('Invalid archive policy')
        root = Path(p['root'])
        if not root.is_absolute() or root.is_symlink() or root.resolve().is_relative_to(self.data.resolve()):
            raise ValueError('Archive root must be an external absolute directory')
        return root/p['instance']

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.index, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS bodies(sha TEXT PRIMARY KEY, bytes INTEGER, packed INTEGER, remote TEXT, verified REAL, touched REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS aliases(path TEXT PRIMARY KEY, sha TEXT, campaign TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS alias_sha ON aliases(sha)')
            db.execute('CREATE TABLE IF NOT EXISTS owners(sha TEXT,campaign TEXT,PRIMARY KEY(sha,campaign))')
            yield db
            db.commit()
        except BaseException:
            db.rollback();raise
        finally:db.close()

    @contextlib.contextmanager
    def lock(self, sha):
        if not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('Invalid artifact digest')
        folder=self.data/'locks'/'cold';folder.mkdir(parents=True,exist_ok=True)
        with (folder/sha).open('a') as stream:
            deadline=time.monotonic()+(self.policy or {}).get('lockTimeoutSeconds',5)
            while True:
                try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.monotonic()>=deadline:raise TimeoutError('Archive object is busy; retry')
                    time.sleep(0.05)
            yield

    def safe(self, relative):
        p=Path(relative)
        if p.is_absolute() or '..' in p.parts or not p.parts:raise ValueError('Invalid archive alias')
        result=self.data/p
        for parent in [result,*result.parents]:
            if parent==self.data:break
            if parent.is_symlink():raise ValueError('Archive alias traverses a symlink')
        return result

    def body(self, sha):
        if not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('Invalid artifact digest')
        return self.safe('artifacts/sha256/'+sha[:2]+'/'+sha)

    def remote(self, sha, recorded=None):
        root=self.root();file=root/'objects'/sha[:2]/(sha+'.gz')
        if recorded is not None and str(file)!=recorded:raise ValueError('Archive location differs from policy')
        for p in (root.parent,root,root/'objects',file.parent,file):
            if p.is_symlink():raise ValueError('Archive path traverses a symlink')
        return file

    def _verify_remote(self, file, sha, size):
        if file.is_symlink():raise ValueError('Archive object is a symlink')
        digest=hashlib.sha256();count=0
        with gzip.open(file,'rb') as stream:
            while chunk:=stream.read(1024*1024):
                count+=len(chunk)
                if count>size:raise ValueError('Archive object exceeds expected size')
                digest.update(chunk)
        if count!=size or digest.hexdigest()!=sha:raise ValueError('Archive integrity mismatch')

    def publish(self, sha, aliases, owners):
        """Copy, read back, then commit local locators. No deletion here."""
        with self.lock(sha):
            source=self.body(sha)
            with self.db() as db:existing=db.execute('SELECT * FROM bodies WHERE sha=?',(sha,)).fetchone()
            if existing:
                # Eviction is a separate phase and verifies the remote again.
                size=existing['bytes'];remote=self.remote(sha,existing['remote']);packed=existing['packed']
            else:
                before=source.stat();size=before.st_size
                if not stat.S_ISREG(before.st_mode) or source.is_symlink():raise ValueError('Invalid archive source')
                remote=self.remote(sha);folder=remote.parent;root=self.root();folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                used=sum(r[0] for r in self._rows('SELECT packed FROM bodies'))
                if used+size>self.policy.get('maxBytes',200*1024**3):raise OSError('Archive budget exhausted')
                if shutil.disk_usage(root).free<size+self.policy.get('minFreeBytes',10*1024**3):raise OSError('Archive free-space reserve reached')
                temp=folder/('.upload-'+uuid.uuid4().hex)
                digest=hashlib.sha256();start=time.monotonic();copied=0
                try:
                    with source.open('rb') as inp,temp.open('xb') as raw:
                        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=1) as out:
                            while chunk:=inp.read(1024*1024):
                                digest.update(chunk);out.write(chunk);copied+=len(chunk)
                                rate=self.policy.get('bytesPerSecond',32*1024**2)
                                if rate:time.sleep(max(0,copied/rate-(time.monotonic()-start)))
                        raw.flush();os.fsync(raw.fileno())
                    after=source.stat()
                    if digest.hexdigest()!=sha or (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
                        raise ValueError('Archive source changed')
                    self._verify_remote(temp,sha,size)
                    temp.chmod(0o600);os.replace(temp,remote)
                    fd=os.open(folder,os.O_RDONLY)
                    try:os.fsync(fd)
                    finally:os.close(fd)
                    packed=remote.stat().st_size
                finally:temp.unlink(missing_ok=True)
            with self.db() as db:
                db.execute('INSERT OR IGNORE INTO bodies VALUES(?,?,?,?,?,?)',(sha,size,packed,str(remote),time.time(),0))
                for campaign in owners:db.execute('INSERT OR IGNORE INTO owners VALUES(?,?)',(sha,campaign))
                for relative,campaign in aliases:
                    self.safe(relative)
                    prior=db.execute('SELECT sha FROM aliases WHERE path=?',(relative,)).fetchone()
                    if prior and prior['sha']!=sha:raise ValueError('Archive alias content changed')
                    db.execute('INSERT OR IGNORE INTO aliases VALUES(?,?,?)',(relative,sha,campaign))
                changed=db.total_changes>0
            # A self-contained receipt precedes eviction. The remote side has
            # plain closed files, never a live SQLite database on NFS.
            if changed or not remote.with_suffix('.json').exists():self.receipt(sha)
        return size

    def receipt(self, sha):
        with self.db() as db:
            body=dict(db.execute('SELECT * FROM bodies WHERE sha=?',(sha,)).fetchone())
            aliases=[dict(r) for r in db.execute('SELECT * FROM aliases WHERE sha=?',(sha,))]
            owners=[r[0] for r in db.execute('SELECT campaign FROM owners WHERE sha=?',(sha,))]
        remote=self.remote(sha,body['remote'])
        atomic_json(remote.with_suffix('.json'),{'version':1,'dataRoot':str(self.data),'body':body,'aliases':aliases,'owners':owners})
        fd=os.open(remote.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def _rows(self, sql, args=()):
        with self.db() as db:return [dict(r) if len(r.keys())>1 else tuple(r) for r in db.execute(sql,args)]

    def _restore(self, sha):
        target=self.body(sha)
        if target.exists() or not self.index.exists():return target
        with self.lock(sha):
            if target.exists():return target
            with self.db() as db:row=db.execute('SELECT * FROM bodies WHERE sha=?',(sha,)).fetchone()
            if not row:raise FileNotFoundError(target)
            reserve=(self.policy or {}).get('localReserveBytes',2*1024**3)
            if shutil.disk_usage(self.data).free<row['bytes']+reserve:raise OSError('Insufficient local capacity to restore evidence')
            target.parent.mkdir(parents=True,exist_ok=True)
            for pending in target.parent.glob('.restore-'+sha+'-*'):pending.unlink()
            fd,name=tempfile.mkstemp(prefix='.restore-'+sha+'-',dir=target.parent)
            try:
                digest=hashlib.sha256();count=0
                remote=self.remote(sha,row['remote'])
                if remote.is_symlink():raise ValueError('Archive object is a symlink')
                with os.fdopen(fd,'wb') as out,gzip.open(remote,'rb') as inp:
                    while chunk:=inp.read(1024*1024):
                        count+=len(chunk)
                        if count>row['bytes']:raise ValueError('Archive size mismatch')
                        out.write(chunk);digest.update(chunk)
                    out.flush();os.fsync(out.fileno())
                if count!=row['bytes'] or digest.hexdigest()!=sha:raise ValueError('Archive integrity mismatch')
                os.chmod(name,0o444);os.replace(name,target)
                with self.db() as db:db.execute('UPDATE bodies SET touched=? WHERE sha=?',(time.time(),sha))
            finally:
                if os.path.exists(name):os.unlink(name)
        return target

    def materialize(self, sha):
        target=self.body(sha)
        if target.exists() or not self.index.exists():return target
        from .cold_io import restore
        restore(self,sha)
        return target

    def touch(self, sha):
        if self.index.exists():
            with self.db() as db:db.execute('UPDATE bodies SET touched=? WHERE sha=?',(time.time(),sha))

    def link(self, sha, target):
        target=Path(target)
        for _ in range(3):
            source=self.materialize(sha)
            with self.lock(sha):
                if not source.exists():continue
                target.parent.mkdir(parents=True,exist_ok=True)
                try:os.link(source,target)
                except FileExistsError:
                    if target.is_symlink() or not os.path.samefile(source,target):raise ValueError('Evidence view identity mismatch')
                self.touch(sha)
                return target
        raise OSError('Evidence changed during restoration; retry')

    def read(self, sha):
        for _ in range(3):
            source=self.materialize(sha)
            with self.lock(sha):
                if source.exists():
                    self.touch(sha)
                    return source.read_bytes()
        raise OSError('Evidence changed during restoration; retry')

    def restore_path(self, file):
        file=Path(file)
        if file.exists() or not self.index.exists():return file
        relative=file.relative_to(self.data).as_posix()
        with self.db() as db:row=db.execute('SELECT sha FROM aliases WHERE path=?',(relative,)).fetchone()
        if not row:return file
        return self.link(row['sha'],self.safe(relative))

    def restore_tree(self, directory):
        if not self.index.exists():return
        prefix=Path(directory).relative_to(self.data).as_posix()+'/'
        with self.db() as db:rows=db.execute('SELECT path FROM aliases WHERE substr(path,1,?)=?',(len(prefix),prefix)).fetchall()
        for row in rows:self.restore_path(self.data/row['path'])

    def prepare_references(self, store, campaign, payload):
        """Warm explicitly named evidence before entering a business write transaction."""
        if not self.index.exists():return
        refs=set()
        def collect(value):
            if isinstance(value,dict):
                if isinstance(value.get('evidenceId'),str):refs.add(value['evidenceId'])
                if isinstance(value.get('evidenceRefs'),list):refs.update(x for x in value['evidenceRefs'] if isinstance(x,str))
                for child in value.values():collect(child)
            elif isinstance(value,list):
                for child in value:collect(child)
        collect(payload)
        with store.connection() as db:
            rows=[db.execute('SELECT data FROM evidence WHERE campaign=? AND id=?',(campaign,ref)).fetchone() for ref in refs]
        for row in rows:
            if not row:continue  # The business validator reports invalid references.
            evidence=json.loads(row[0]);sha=evidence.get('sha256')
            if sha and Path(evidence.get('path',''))==self.body(sha):self.read(sha)

    def evict(self, sha, store):
        """Unknown links, active views and recently read objects stay resident."""
        with self.lock(sha):
            with self.db() as db:
                row=db.execute('SELECT * FROM bodies WHERE sha=?',(sha,)).fetchone()
                aliases=db.execute('SELECT * FROM aliases WHERE sha=?',(sha,)).fetchall()
            if not row or time.time()-row['touched']<(self.policy or {}).get('cacheSeconds',3600):return 0
            source=self.body(sha)
            if not source.exists():return 0
            actual=[]
            for alias in aliases:
                p=self.safe(alias['path'])
                if not p.exists():continue
                if not os.path.samefile(p,source):raise ValueError('Archive alias identity changed')
                if alias['path'].startswith('campaigns/'):
                    c=store.get('campaigns',alias['campaign'])
                    if c['state'] not in ('finished','failed'):return 0
                actual.append(p)
            before=source.stat()
            if before.st_nlink!=len(actual)+1:return 0
            self._verify_remote(self.remote(sha,row['remote']),sha,row['bytes'])
            # Publication/read views use this same local object lock. Network
            # verification above never holds it or a SQLite write transaction.
            from .objects import Objects
            with Objects(self.data).locked():
                if source.stat().st_nlink!=len(actual)+1:return 0
                for p in actual:
                    if not p.exists() or not os.path.samefile(p,source):return 0
                for p in actual:p.unlink()
                source.unlink()
            return before.st_blocks*512

    def cycle(self, store):
        if not self.configured():return
        self.validate()
        candidates={};by_inode={};campaigns={c['id']:c for c in store.list('campaigns')}
        for cid,c in campaigns.items():
            if c['state']=='deleting':continue
            for trial in store.runs(cid):
                if trial['state'] not in TERMINAL or not trial.get('output'):continue
                if trial.get('evidenceIndex',{}).get('state') not in (None,'complete'):continue
                output=Path(trial['output'])
                if not output.is_relative_to(self.data):continue
                marker=output/'artifact-archive.json'
                if not marker.exists():continue
                for rel,info in json.loads(marker.read_text())['files'].items():
                    # Keep official outcomes, manifests and recovery metadata hot.
                    if info['bytes']<(self.policy or {}).get('minObjectBytes',65536):continue
                    if '/public_job_results/' not in rel and 'gateway-audit.jsonl' not in rel:continue
                    sha=info['sha256'];file=self.safe((output/rel).relative_to(self.data).as_posix())
                    item=candidates.setdefault(sha,{'aliases':set(),'owners':set()})
                    item['aliases'].add((file.relative_to(self.data).as_posix(),cid));item['owners'].add(cid)
                    body=self.body(sha)
                    if body.exists():s=body.stat();by_inode[(s.st_dev,s.st_ino)]=sha
        # Include published views only for completed activities. Active views pin
        # their inode even when their content also belongs to a closed Trial.
        for cid,c in campaigns.items():
            if c['state'] not in ('finished','failed'):continue
            root=self.data/'campaigns'/cid/'meta-files'
            for base,dirs,files in os.walk(root,followlinks=False):
                dirs[:]=[d for d in dirs if not (Path(base)/d).is_symlink()]
                for name in files:
                    p=Path(base)/name
                    if p.is_symlink():continue
                    s=p.stat();sha=by_inode.get((s.st_dev,s.st_ino))
                    if sha:candidates[sha]['aliases'].add((p.relative_to(self.data).as_posix(),cid))
        for row in store.list('evidence'):
            if row['sha256'] in candidates:candidates[row['sha256']]['owners'].add(row['campaignId'])
        copied=freed=0
        for sha,item in candidates.items():
            if any(store.deletion(c) for c in item['owners']):continue
            if not self.body(sha).exists():continue
            copied+=self.publish(sha,item['aliases'],item['owners'])
            if self.policy.get('evict',False):freed+=self.evict(sha,store)
            atomic_json(self.state,{'state':'running','heartbeat':time.time(),'objects':len(candidates),'copiedBytes':copied,'reclaimedBytes':freed})
        atomic_json(self.state,{'state':'complete','finishedAt':time.time(),'objects':len(candidates),'copiedBytes':copied,'reclaimedBytes':freed})

    def delete_campaign(self, campaign, store):
        if not self.index.exists():return
        with self.db() as db:shas=[r[0] for r in db.execute('SELECT sha FROM owners WHERE campaign=?',(campaign,))]
        for sha in shas:
            with self.lock(sha):
                # Explicit adoptions may have been made since the last archive scan.
                with store.connection() as db:
                    refs=[r[0] for r in db.execute("SELECT DISTINCT campaign FROM evidence WHERE campaign<>? AND json_extract(data,'$.sha256')=? UNION SELECT DISTINCT campaign FROM source_adoptions WHERE campaign<>? AND json_extract(data,'$.sha256')=?",(campaign,sha,campaign,sha))]
                with self.db() as db:
                    others=[r[0] for r in db.execute('SELECT campaign FROM owners WHERE sha=? AND campaign<>?',(sha,campaign))]
                    row=db.execute('SELECT * FROM bodies WHERE sha=?',(sha,)).fetchone()
                if not refs and not others and row:
                    remote=self.remote(sha,row['remote'])
                    if remote.is_symlink():raise ValueError('Archive object is a symlink')
                    remote.unlink(missing_ok=True)
                    remote.with_suffix('.json').unlink(missing_ok=True)
                with self.db() as db:
                    db.execute('DELETE FROM owners WHERE campaign=? AND sha=?',(campaign,sha))
                    db.execute('DELETE FROM aliases WHERE campaign=? AND sha=?',(campaign,sha))
                    for cid in refs:db.execute('INSERT OR IGNORE INTO owners VALUES(?,?)',(sha,cid))
                    if not refs and not others:db.execute('DELETE FROM bodies WHERE sha=?',(sha,))
                if refs or others:self.receipt(sha)

    def snapshot(self):
        result={'enabled':self.configured(),'state':'disabled' if not self.configured() else 'idle','objectCount':0,'originalBytes':0,'storedBytes':0}
        if self.state.exists():result.update(json.loads(self.state.read_text()))
        if not self.configured():result['state']='disabled'
        if result['state']=='running' and time.time()-result.get('heartbeat',0)>300:result['state']='delayed'
        if self.index.exists():
            with self.db() as db:
                r=db.execute('SELECT count(*),coalesce(sum(bytes),0),coalesce(sum(packed),0) FROM bodies').fetchone()
            result.update(objectCount=r[0],originalBytes=r[1],storedBytes=r[2])
        return result
