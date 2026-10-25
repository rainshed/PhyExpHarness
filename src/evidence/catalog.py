"""Immutable paged evidence trees, reusable by frozen native Meta protocols."""
import fcntl
import hashlib
import json
from .files import atomic_json
from .snapshots import Snapshots
from .objects import enabled
from src.control.store import encoded

class EvidenceCatalog:
    def __init__(self,receipts):
        self.receipts=receipts;self.store=receipts.store;self.service=receipts.service

    def tree(self,campaign,filters=None):
        filters=filters or {};key=hashlib.sha256(encoded(filters).encode()).hexdigest()
        directory=self.service.data/'campaigns'/campaign/'evidence-catalogs'
        directory.mkdir(parents=True,exist_ok=True)
        with (directory/(key+'.lock')).open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            with self.store.read_snapshot(),self.store.connection() as db:
                version=db.execute('SELECT version FROM evidence_versions WHERE campaign=?',(campaign,)).fetchone()
                stats=tuple(db.execute('SELECT count(*),max(rowid) FROM evidence WHERE campaign=?',(campaign,)).fetchone())
                revision=[version[0] if version else 0,*stats]
                cache=directory/(key+'.json')
                if cache.exists():
                    value=json.loads(cache.read_text())
                    if value['revision']==revision:return value
                tree=Snapshots(self.receipts.files,campaign);shards=[];offset=0;unavailable=0;total=0;legacy=[]
                shared=enabled(self.store.get('campaigns',campaign)['config'])
                while True:
                    page=self.service.evidence.page(campaign,**filters,offset=offset,limit=100)
                    values=[self.receipts.evidence(campaign,e) for e in page['items']]
                    unavailable+=sum(e['availability']!='available' for e in values);total=page['total']
                    if not shared:legacy.extend(values)
                    if shared and values:shards.append({'bucket':str(offset),**tree.save({'format':'query-tree-v1','kind':'items',
                        'items':[{'position':offset+i,'value':tree.node(e)} for i,e in enumerate(values)]})})
                    if page['nextOffset'] is None:break
                    offset=page['nextOffset']
                result={'revision':revision,'total':total,'unavailableCount':unavailable,
                    'items':tree.save({'format':'query-tree-v1','kind':'list','count':total,'shards':shards}) if shared else legacy}
                atomic_json(cache,result)
                return result
