import hashlib
import json
import os
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from src.control.storage import Storage,GiB
from src.control.deletion import ActivityAccess
from src.control.store import Store
from src.evidence.objects import POLICY

Usage=namedtuple('Usage','total used free')

class StorageCapacityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.store=Store(self.root/'control.sqlite');self.store.put('campaigns',{'id':'c','config':{'storagePolicy':POLICY},'state':'running'})
        self.service=SimpleNamespace(data=self.root,store=self.store,access=ActivityAccess(),_process_alive=lambda *a:False)
        self.storage=Storage(self.service)
        self.disk=patch('src.control.storage.shutil.disk_usage',return_value=Usage(100*GiB,10*GiB,90*GiB));self.fake_disk=self.disk.start();self.addCleanup(self.disk.stop)
    def test_admission_reserves_inflight_closeout_and_recovers_with_hysteresis(self):
        self.fake_disk.return_value=Usage(100*GiB,89*GiB,11*GiB)
        self.store.put('trials',{'id':'t','campaignId':'c','state':'running'})
        self.assertFalse(self.storage.permit('c','trial')) # strict >= data floor + two trials
        self.fake_disk.return_value=Usage(100*GiB,87*GiB,13*GiB)
        self.assertTrue(self.storage.permit('c','trial'))
        events=self.store.events('c');self.assertEqual([e['type'] for e in events],['storage_waiting','storage_ready'])
    def test_data_and_campaign_budget_block_without_changing_lifecycle_or_clock(self):
        file=self.root/'campaigns/c/workspace/out';file.parent.mkdir(parents=True);file.write_bytes(b'x'*20000)
        self.storage.configure({'maxCampaignBytes':10000,'resumeMarginBytes':1000})
        before=self.store.get('campaigns','c');self.assertFalse(self.storage.permit('c'))
        self.assertEqual(self.store.get('campaigns','c'),before)
        file.unlink();self.storage.inventory(force=True);self.assertTrue(self.storage.permit('c'))
    def test_closed_trial_is_shared_active_and_external_paths_are_untouched(self):
        folder=self.root/'trials/launch';folder.mkdir(parents=True);body=folder/'result';body.write_bytes(b'evidence')
        sha=hashlib.sha256(body.read_bytes()).hexdigest();(folder/'archive-manifest.json').write_text(json.dumps({'files':{'result':{'sha256':sha,'bytes':8}}}))
        self.store.put('trials',{'id':'t','campaignId':'c','state':'running','output':str(folder)})
        with patch('src.control.storage.subprocess.check_output',return_value=''):
            self.storage.maintain(force=True);self.assertFalse((folder/'artifact-archive.json').exists())
            row=self.store.get('trials','t');row['state']='finished';self.store.put('trials',row)
            self.storage.maintain(force=True)
        self.assertTrue(os.path.samefile(body,self.storage.objects.path(sha)))
    def test_bad_policy_is_rejected_and_shared_inodes_are_counted_once(self):
        a=self.root/'a';a.write_bytes(b'x'*20000);os.link(a,self.root/'b');self.storage.inventory(force=True)
        self.assertLess(self.storage.metrics['groups']['database-and-state'],2*a.stat().st_blocks*512+(self.root/'control.sqlite').stat().st_blocks*512+10000)
        with self.assertRaises(ValueError):self.storage.configure({'minFreeBytes':-1})
        with self.assertRaises(ValueError):self.storage.configure({'scanSeconds':1})
        with self.assertRaises(ValueError):self.storage.configure({'unknown':True})
    def test_cache_current_generation_and_references_survive(self):
        parent=self.root/'cache/dependencies';parent.mkdir(parents=True);key='a'*64
        old=parent/(key+'-'+'b'*32);old.mkdir();(old/'file').write_text('old');os.utime(old,(0,0))
        current=parent/(key+'-'+'c'*32);current.mkdir();(parent/(key+'.json')).write_text(json.dumps({'generation':current.name}))
        (self.root/'keep').symlink_to(old/'file')
        self.storage.prune_caches('',1000000);self.assertTrue(old.exists())
        (self.root/'keep').unlink();self.storage.prune_caches('',1000000)
        self.assertFalse(old.exists());self.assertTrue(current.exists())

class StorageIntegrationTests(unittest.TestCase):
    def setUp(self):
        from control_test import ControlTests
        ControlTests.setUp(self)
        row=self.service.store.get('campaigns',self.c);row['config']['storagePolicy']=POLICY;self.service.store.put('campaigns',row)
    def tearDown(self):
        from control_test import ControlTests
        ControlTests.tearDown(self)
    def test_user_policy_and_model_admission_wait_are_separate_from_token_ledger(self):
        result=self.client.post('/storage/policy',json={'maxDataBytes':30*GiB});self.assertEqual(result.status_code,200)
        lease,token=self.service.lease(self.c,'meta',9999999999)
        headers={'Authorization':'Bearer '+token}
        self.assertEqual(self.client.put('/storage/policy',headers=headers,json={'maxDataBytes':60*GiB}).status_code,403)
        with patch('src.control.storage.shutil.disk_usage',return_value=Usage(100*GiB,99*GiB,GiB)):
            result=self.client.post('/accounting/'+lease['id']+'/reserve',headers=headers,json={'id':'request','reservedTokens':300000,'admissionVersion':1})
            self.assertEqual(result.status_code,429);self.assertEqual(result.json()['code'],'storage_capacity_wait')
            self.assertEqual(self.service.store.list('usage',self.c),[])
            self.assertTrue(self.client.get('/campaigns/'+self.c).json()['storage']['waiting'])
    def test_capacity_blocks_meta_process_start_before_creating_a_session(self):
        from src.control.meta import MetaDriver
        driver=MetaDriver(self.service)
        with patch('src.control.storage.shutil.disk_usage',return_value=Usage(100*GiB,99*GiB,GiB)),patch.object(driver,'_start') as start:
            driver.start(self.c);start.assert_not_called()
        self.assertEqual(self.service.store.list('meta_sessions',self.c),[])
    def test_complete_segmented_evidence_and_archive_use_one_body(self):
        import subprocess
        from src.evidence.library import EvidenceLibrary
        from src.evidence.files import FileViews
        root=self.service.data/'trials'/'segmented';folder=root/'harbor/t/phyexp';folder.mkdir(parents=True)
        log=folder/'model-audit.jsonl';body='完整工具结果🙂\n'*20
        script="import {appendLog} from './src/execution/host/log_store.mjs';appendLog(process.argv[1],process.argv[2],{segmentBytes:20});"
        subprocess.run(['node','--input-type=module','-e',script,str(log),body],check=True)
        library=EvidenceLibrary(self.service.store,self.service.data)
        rows=library.ingest_complete({'id':'segmented','campaignId':self.c,'output':str(root)}, {})
        compressed=next(r for r in rows if r['source']['archive'].endswith('.gz'))
        self.assertEqual(library.read(self.c,compressed['id'])['text'],body)
        self.assertEqual(next(r for r in rows if r['source']['archive'].endswith('.jsonl'))['source']['format'],'segmented-log-tail')
        view=FileViews(self.service).evidence(self.c,compressed)
        self.service.storage.objects.archive(root)
        self.assertTrue(os.path.samefile(compressed['path'],root/compressed['source']['archive']))
        self.assertTrue(os.path.samefile(compressed['path'],FileViews(self.service).directory(self.c)/view['path'].lstrip('/')))
    def test_adopted_source_keeps_scope_and_content_addressed_view(self):
        from src.evidence.library import EvidenceLibrary
        from src.evidence.files import FileViews
        target=self.service.store.get('campaigns',self.c)
        self.service.store.put('campaigns',{**target,'id':'source'})
        library=EvidenceLibrary(self.service.store,self.service.data)
        source=library.add('source',None,'test','historical result',{'archive':'source.txt'})
        adopted=self.service.adoptions.adopt(self.c,'source','evidence',source['id'],'研究来源','meta-research','shared-adoption')
        row=self.service.store.get('evidence',adopted['evidenceId'])
        descriptor=FileViews(self.service).evidence(self.c,row)
        self.assertTrue(descriptor['path'].startswith('/evidence/objects/'))
        self.assertTrue(os.path.samefile(source['path'],row['path']))
        self.assertEqual(self.service.adoptions.read(self.c,adopted['id'])['text'],'historical result')
        self.assertEqual(library.read(self.c,row['id'])['text'],'historical result')
        with self.assertRaises(ValueError):library.read('source',row['id'])
