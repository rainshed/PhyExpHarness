import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from src.control.store import Store
from src.evidence.files import FileViews
from src.evidence.objects import POLICY
from src.evidence.snapshots import Snapshots


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.data=Path(self.tmp.name);self.store=Store(self.data/'control.sqlite')
        self.store.put('campaigns',{'id':'c','config':{'storagePolicy':POLICY}})
        self.files=FileViews(SimpleNamespace(store=self.store,data=self.data));self.tree=Snapshots(self.files,'c')

    def load(self,ref):return json.loads((self.files.directory('c')/ref['file']['path'].lstrip('/')).read_text())
    def expand(self,value):
        if not isinstance(value,dict) or value.get('format')!='query-tree-v1' or 'file' not in value:return value
        node=self.load(value)
        if node['kind']=='object':return {k:self.expand(v) for k,v in node['fields'].items()}
        if node['kind']=='value':return node['value']
        pairs=[item for shard in node['shards'] for item in self.load(shard)['items']]
        return [self.expand(item['value']) for item in sorted(pairs,key=lambda i:i['position'])]
    def publish(self,rows):return self.tree.publish('campaign_status',{}, {'evidence':rows,'state':'running'})
    def body(self,file):return json.loads((self.files.directory('c')/file['path'].lstrip('/')).read_text())
    def test_repeated_query_and_return_to_prior_state_share_all_content(self):
        rows=[{'id':str(i),'description':'payload '*100} for i in range(600)]
        first=self.publish(rows);before=set((self.data/'artifacts').rglob('*'))
        self.assertEqual(self.publish(rows),first);self.assertEqual(before,set((self.data/'artifacts').rglob('*')))
        changed=[*rows];changed[2]={**rows[2],'description':'changed'};second=self.publish(changed)
        self.assertNotEqual(first['sha256'],second['sha256']);self.assertEqual(self.publish(rows),first)
        self.assertEqual(self.expand(self.body(first)['data']['evidence']),rows)
        self.assertEqual(self.expand(self.body(second)['data']['evidence']),changed)
        a=self.load(self.body(first)['data']['evidence']);b=self.load(self.body(second)['data']['evidence'])
        self.assertEqual(sum(x!=y for x,y in zip(a['shards'],b['shards'])),1)
        self.assertLess(first['bytes'],4096)
    def test_snapshot_uses_one_sqlite_read_transaction_and_rejects_writes(self):
        with self.store.read_snapshot():
            before=self.store.get('campaigns','c')
            db=sqlite3.connect(self.store.path);db.execute("UPDATE campaigns SET data=? WHERE id='c'",(json.dumps({**before,'new':True}),));db.commit();db.close()
            self.assertEqual(self.store.get('campaigns','c'),before)
            with self.assertRaises(RuntimeError):self.store.put('campaigns',before)
        self.assertTrue(self.store.get('campaigns','c')['new'])
