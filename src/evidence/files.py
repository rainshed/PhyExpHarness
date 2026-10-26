"""Read-only, content-addressed file views shared by native Meta tools and scripts."""
import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
from pathlib import Path
from src.control.store import Refused,encoded
from .objects import Objects, enabled

VERSION='meta-files-v2'
ROOTS=('evidence','materials','sdk','versions','outputs')

def atomic_json(file,value):
    file=Path(file);file.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=file.parent,prefix='.publishing-')
    try:
        with os.fdopen(fd,'w') as stream:stream.write(encoded(value)+'\n')
        os.replace(temp,file)
    finally:
        if os.path.exists(temp):os.unlink(temp)

class FileViews:
    def __init__(self,service):self.service=service;self.store=service.store;self.root=service.data/'campaigns'
    def directory(self,campaign):
        self.store.writable(campaign)
        self.store.get('campaigns',campaign)
        directory=self.root/campaign/'meta-files'
        for name in ROOTS:(directory/name).mkdir(parents=True,exist_ok=True)
        return directory
    def publish(self,campaign,ref,data,*,kind,source,version=None,trial=None,original=None):
        if isinstance(data,str):data=data.encode('utf-8')
        sha=hashlib.sha256(data).hexdigest()
        group='evidence' if kind=='evidence' else 'sdk' if kind=='sdk' else 'versions' if kind in ['version','plugin'] else 'materials'
        suffix=Path(str(source.get('archive',''))) .suffix if isinstance(source,dict) else ''
        if not re.fullmatch(r'\.[a-zA-Z0-9]{1,12}',suffix):suffix='.txt'
        relative=Path('trials')/trial/(sha+suffix) if trial else Path('objects')/(sha+suffix)
        target=self.directory(campaign)/group/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            fd,name=tempfile.mkstemp(dir=target.parent,prefix='.publishing-');os.close(fd);pending=Path(name)
            try:
                # Only immutable evidence objects can be hard-linked; source archives may still change.
                if original:
                    pending.unlink()
                    try:os.link(original,pending)
                    except OSError:shutil.copyfile(original,pending)
                else:
                    if enabled(self.store.get('campaigns',campaign)['config']):
                        objects=Objects(self.service.data)
                        with objects.locked():
                            original=objects._publish([data])
                            pending.unlink();os.link(original,pending)
                    else:pending.write_bytes(data)
                pending.chmod(0o444)
                try:os.link(pending,target)
                except FileExistsError:pass
            finally:pending.unlink(missing_ok=True)
        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise Refused('Published file integrity mismatch')
        try:data.decode('utf-8');encoding='utf-8'
        except UnicodeDecodeError:encoding='binary'
        return {'ref':ref,'kind':kind,'campaignId':campaign,'trialId':trial,'path':'/'+group+'/'+relative.as_posix(),
            'mediaType':mimetypes.guess_type('file'+suffix)[0] or 'application/octet-stream','encoding':encoding,
            'bytes':len(data),'sha256':sha,'source':source,'version':version,'viewVersion':VERSION,
            'availability':'available','completeness':'complete','observedAt':self.store.clock()}
    def evidence(self,campaign,row):
        if row['campaignId']!=campaign:raise Refused('Cross-Campaign evidence')
        file=Path(row['path'])
        if enabled(self.store.get('campaigns',campaign)['config']):
            if file!=Objects(self.service.data).path(row['sha256']) or file.is_symlink() or file.stat().st_size!=row['bytes']:raise Refused('Evidence object identity mismatch')
            suffix=Path(str(row.get('source',{}).get('archive',''))).suffix
            if not re.fullmatch(r'\.[a-zA-Z0-9]{1,12}',suffix):suffix='.txt'
            relative=Path('trials')/row['trialId']/(row['sha256']+suffix) if row.get('trialId') else Path('objects')/(row['sha256']+suffix)
            target=self.directory(campaign)/'evidence'/relative;target.parent.mkdir(parents=True,exist_ok=True)
            try:os.link(file,target)
            except FileExistsError:
                if target.is_symlink() or not os.path.samefile(file,target):raise Refused('Evidence view integrity mismatch')
            return {'ref':'evidence:'+row['id'],'kind':'evidence','campaignId':campaign,'trialId':row['trialId'],'path':'/evidence/'+relative.as_posix(),
                'mediaType':mimetypes.guess_type('file'+suffix)[0] or 'application/octet-stream','encoding':'binary' if suffix=='.gz' else row.get('encoding','utf-8'),
                'bytes':row['bytes'],'sha256':row['sha256'],'source':row['source'],'version':row['policy'],'viewVersion':VERSION,
                'availability':'available','completeness':'complete','observedAt':self.store.clock(),**({'storageEncoding':'gzip'} if suffix=='.gz' else {})}
        data=file.read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['sha256']:raise Refused('Evidence integrity mismatch')
        return self.publish(campaign,'evidence:'+row['id'],data,kind='evidence',source=row['source'],
            version=row['policy'],trial=row['trialId'],original=file)
    def material(self,campaign,row):
        if row['kind']=='evidence':return self.evidence(campaign,self.store.get('evidence',row['evidenceId']))
        if row['availability']!='available':return {k:v for k,v in row.items() if k!='_load'}
        data=row['_load']()
        if row['kind']=='activity' and enabled(self.store.get('campaigns',campaign)['config']):
            from src.control.meta_receipts import stable
            data=encoded(stable(json.loads(data)))
        return self.publish(campaign,row['ref'],data,kind=row['kind'],source=row['source'],version=row.get('version'))
    def refresh(self,campaign):
        if enabled(self.store.get('campaigns',campaign)['config']):
            # Startup/recovery and heartbeat paths must never expand every body.
            # Frozen native tools already expose both complete catalogue queries.
            index={'version':VERSION,'campaignId':campaign,'scope':'navigation','items':[],
                'reading':'材料导航。调用 evidence_list 读取完整不可变证据目录；materials_list 按页查看全部材料。文件入口由查询返回，原始已发布路径继续可用。',
                'catalogs':[{'kind':'evidence','operation':'evidence_list','input':{}},
                            {'kind':'materials','operation':'materials_list','input':{'offset':0,'limit':20}}]}
            atomic_json(self.directory(campaign)/'evidence/index.json',index)
            return index
        items=[]
        for row in self.service.materials._records(campaign):
            try:items.append(self.material(campaign,row))
            except (OSError,ValueError) as error:
                items.append({'ref':row['ref'],'availability':'unavailable','reason':str(error),'completeness':'unavailable'})
        # Descriptors include all files; callers paginate the index, never silently cap it.
        directory=self.directory(campaign);file=directory/'evidence/index.json'
        old=json.loads(file.read_text()) if file.exists() else {}
        signature=hashlib.sha256(encoded([{k:v for k,v in r.items() if k!='observedAt'} for r in items]).encode()).hexdigest()
        index={'version':VERSION,'campaignId':campaign,'revision':old.get('revision',0)+(signature!=old.get('digest')),
            'digest':signature,'items':items,'total':len(items),'complete':all(r['availability']=='available' for r in items)}
        atomic_json(file,index)
        return index
