import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tests.unit.deployment_storage_test import DeploymentStorageTests
from src.control.store import Store, Refused
from src.control.meta_receipts import Receipts, public
from src.control.meta_api import MetaAPI
from src.evidence.library import EvidenceLibrary
from src.evidence.files import FileViews
from src.evidence.objects import POLICY
from src.evidence.catalog import EvidenceCatalog
from src.evidence.deployment_views import EvidenceViews
from src.evidence.snapshots import Snapshots


class DeploymentReportingTests(unittest.TestCase):
    def setUp(self):
        DeploymentStorageTests.setUp(self)
        self.store=Store(self.data/'control.sqlite')
        self.store.put('campaigns',{'id':'c','state':'running','config':{'storagePolicy':POLICY}})
        self.store.put('campaigns',{'id':'other','state':'running','config':{'storagePolicy':POLICY}})
        self.service=SimpleNamespace(data=self.data,store=self.store)
        self.service.evidence=EvidenceLibrary(self.store,self.data)
        self.files=FileViews(self.service)
        self.receipts=Receipts(SimpleNamespace(service=self.service,store=self.store,files=self.files))

    def row(self,trial='t',text='immutable result',source=None):
        return self.service.evidence.add('c',trial,'raw-artifact',text,source or {'archive':'result.json'})

    def expand(self,ref):
        if not isinstance(ref,dict) or ref.get('format')!='query-tree-v1' or 'file' not in ref:return ref
        node=json.loads((self.files.directory('c')/ref['file']['path'].lstrip('/')).read_text())
        if node['kind']=='value':return node['value']
        if node['kind']=='object':return {k:self.expand(v) for k,v in node['fields'].items()}
        items=[item for shard in node['shards'] for item in json.loads((self.files.directory('c')/shard['file']['path'].lstrip('/')).read_text())['items']]
        return [self.expand(item['value']) for item in sorted(items,key=lambda x:x['position'])]

    def test_batch_preserves_descriptor_and_validates_existing_inode(self):
        row=self.row();expected=self.files.evidence('c',row)
        projected=self.receipts.evidence_many('c',[row])[0]['file']
        self.assertEqual({k:v for k,v in expected.items() if k!='observedAt'},projected)
        target=self.files.directory('c')/projected['path'].lstrip('/')
        self.assertTrue(os.path.samefile(target,row['path']))
        target.unlink();target.write_text('changed result')
        self.assertEqual(self.receipts.evidence_many('c',[row])[0]['availability'],'unavailable')

    def test_batch_rejects_cross_campaign_and_symlink_view(self):
        row=self.row();views=EvidenceViews(self.files,'c')
        with self.assertRaises(Refused):views.project({**row,'campaignId':'other'})
        descriptor=views.project(row);target=self.files.directory('c')/descriptor['path'].lstrip('/')
        target.unlink();target.symlink_to(row['path'])
        with self.assertRaises(Refused):views.project(row)
        with self.assertRaises(Refused):views.project({**row,'trialId':'../outside'})

    def test_catalog_streams_all_rows_once_and_preserves_filter_and_order(self):
        rows=[self.row('t' if i%2 else 'u',str(i),{'archive':str(i)+'.json'}) for i in range(1030)]
        other=self.service.evidence.add('other','t','raw-artifact','foreign',{'archive':'other'})
        with patch.object(self.service.evidence,'page',side_effect=AssertionError('Repeated offset scans are forbidden')):
            catalog=EvidenceCatalog(self.receipts).tree('c',{'trialId':'t'})
        actual=self.expand(catalog['items']);expected=[r['id'] for r in rows if r['trialId']=='t']
        self.assertEqual([r['id'] for r in actual],expected)
        self.assertEqual(catalog['total'],len(expected));self.assertEqual(catalog['unavailableCount'],0)
        self.assertNotIn(other['id'],[r['id'] for r in actual])
        self.assertEqual(EvidenceCatalog(self.receipts).tree('c',{'trialId':'t'}),catalog)

    def test_large_inline_records_expand_exactly_without_per_record_files(self):
        rows=[{'id':str(i),'source':{'description':'evidence detail '*800},'array':[i,i+1]} for i in range(300)]
        tree=Snapshots(self.files,'c');result=tree.node(rows)
        self.assertEqual(self.expand(result),rows)
        # One hash bucket shard and one root, rather than multiple files per row.
        self.assertLessEqual(len(tree.saved),257)

    def test_terminal_campaign_keeps_archive_touch_path(self):
        row=self.row();campaign=self.store.get('campaigns','c');campaign['state']='finished';self.store.put('campaigns',campaign)
        with patch.object(self.files,'evidence',wraps=self.files.evidence) as original:
            self.assertEqual(self.receipts.evidence_many('c',[row])[0]['availability'],'available')
            original.assert_called_once()

    def test_facts_source_identity_remains_available_without_discarded_copy(self):
        import hashlib
        from src.control.store import encoded
        row=self.row()
        facts={'campaign':{'id':'c'},'trials':[],'evidence':[{k:v for k,v in row.items() if k!='path'}]}
        self.service.reports=SimpleNamespace(facts=lambda *args:facts)
        api=MetaAPI(self.service)
        for protocol in ('meta-tools-v9','meta-tools-v10'):
            with self.subTest(protocol=protocol),patch('src.control.meta_api.version',return_value=protocol),patch.object(api.files,'publish',side_effect=AssertionError('Discarded raw view should not be published')):
                result=api._call('c','report_get_facts',{})
        self.assertEqual(result['factsId'],hashlib.sha256(encoded(facts).encode()).hexdigest())
        saved=json.loads((self.data/'campaigns/c/report-facts'/(result['factsId']+'.json')).read_text())
        self.assertEqual(saved['facts'],facts)

    def test_global_facts_keep_exact_identity_and_all_sharded_metadata(self):
        import hashlib
        from src.control.store import encoded
        from src.control.deployment_facts import global_facts
        row={k:v for k,v in self.row().items() if k!='path'}
        rows=[{**row,'id':'e'+str(i),'source':{'archive':'result.json','detail':'detail '*20}} for i in range(2051)]
        rows[1024]['source']['detail']='large record '*12000
        facts={'campaign':{'id':'c'},'trials':[],'evidence':rows,'detail':{'host':'/var/tmp/private','original':'kept'}}
        self.service.reports=SimpleNamespace(facts=lambda *args:facts)
        api=MetaAPI(self.service)
        with patch.object(api.receipts,'report_navigation',return_value={}),patch.object(api.files,'evidence',side_effect=AssertionError('Global metadata must not touch every body')):
            result=global_facts(api,'c')
        self.assertEqual(result['factsId'],hashlib.sha256(encoded(facts).encode()).hexdigest())
        saved=(self.data/'campaigns/c/report-facts'/(result['factsId']+'.json')).read_text()
        self.assertEqual(saved,encoded({'batchId':None,'facts':facts})+'\n')
        root=json.loads((self.files.directory('c')/result['file']['path'].lstrip('/')).read_text())
        self.assertEqual(self.expand(root['data']),public(facts))
        self.assertIn('evidence_read({id: record.id})',root['reading'])
        self.assertIn('not an eager body-availability assertion',root['reading'])

    def test_final_report_view_reuses_facts_and_preserves_complete_report(self):
        from src.control.deployment_facts import facts_node,report_view
        facts={'evidence':[{k:v for k,v in self.row().items() if k!='path'}],'campaign':{'id':'c'}}
        node=facts_node(self.files,'c','a'*64,facts)
        row={'id':'report-one','kind':'final','facts':facts,'factsSha256':'a'*64,'analysis':{'summary':'full report'},'tables':{'all':[1,2,3]}}
        ref=report_view(self.receipts,'c',row)
        root=json.loads((self.files.directory('c')/ref['path'].lstrip('/')).read_text())
        self.assertEqual(root['data']['facts'],node)
        self.assertEqual({k:self.expand(v) for k,v in root['data'].items()},public(row))

    def test_cached_facts_view_corruption_and_path_escape_are_rejected(self):
        from src.control.deployment_facts import facts_node
        facts={'evidence':[]};node=facts_node(self.files,'c','b'*64,facts)
        target=self.files.directory('c')/node['file']['path'].lstrip('/')
        target.chmod(0o600);target.write_text('{}')
        with self.assertRaises(Refused):facts_node(self.files,'c','b'*64,facts)
        index=self.data/'campaigns/c/report-views'/('b'*64+'.json')
        saved=json.loads(index.read_text());saved['node']['file']['path']='/materials/objects/../../outside'
        index.write_text(json.dumps(saved))
        with self.assertRaises(Refused):facts_node(self.files,'c','b'*64,facts)

    def test_metadata_cache_reuses_unchanged_rows_but_preserves_changed_content(self):
        from src.control.deployment_facts import facts_node
        facts={'evidence':[{'id':'e','source':{'value':'old'}}],'campaign':{'state':'running'}}
        first=facts_node(self.files,'c','c'*64,facts)
        next_facts={**facts,'campaign':{'state':'closing'}}
        second=facts_node(self.files,'c','d'*64,next_facts)
        read=lambda ref:json.loads((self.files.directory('c')/ref['file']['path'].lstrip('/')).read_text())
        self.assertEqual(read(first)['fields']['evidence'],read(second)['fields']['evidence'])
        changed={**next_facts,'evidence':[{'id':'e','source':{'value':'new'}}]}
        third=facts_node(self.files,'c','e'*64,changed)
        self.assertNotEqual(read(second)['fields']['evidence'],read(third)['fields']['evidence'])
        self.assertEqual(self.expand(third),changed)

    def test_dispatch_preserves_batch_scope_and_legacy_path(self):
        self.service.reports=SimpleNamespace(facts=lambda campaign,batch=None:{'evidence':[],'campaign':{'id':'c'},'scope':batch})
        api=MetaAPI(self.service)
        with patch.object(api.receipts,'report_navigation',return_value={}):
            result=api.receipts.run('c','report_get_facts',{})
            self.assertIsNone(result['batchId']);self.assertIn('factsId',result)
            result=api.receipts.run('c','report_get_facts',{'batchId':'one'})
            self.assertEqual(result['batchId'],'one')
            raw=json.loads((self.data/'campaigns/c/report-facts'/(result['factsId']+'.json')).read_text())
            self.assertEqual(raw['batchId'],'one');self.assertEqual(raw['facts']['scope'],'one')
        with patch('src.execution.host.storage_layout.managed',return_value=False):
            with patch.object(api,'_call',side_effect=RuntimeError('batch path reached')):
                with self.assertRaisesRegex(RuntimeError,'batch path reached'):
                    api.receipts.run('c','report_get_facts',{'batchId':'one'})


if __name__=='__main__':unittest.main()
