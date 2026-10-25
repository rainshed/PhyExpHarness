import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.control.store import Store
from src.evidence.objects import Objects, atomic_json
from src.evidence.cold import ColdArchive
from src.evidence.library import EvidenceLibrary
from src.evidence.files import FileViews

class ColdTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name);self.data=base/'local';self.data.mkdir();self.remote=base/'remote';self.remote.mkdir()
        self.store=Store(self.data/'control.sqlite')
        self.store.put('campaigns',{'id':'c','state':'finished','config':{'storagePolicy':'shared-artifacts-v1'}})
        self.policy={'version':1,'enabled':True,'root':str(self.remote),'instance':'test','evict':True,
            'bytesPerSecond':0,'minFreeBytes':1,'localReserveBytes':1,'maxBytes':1024**3,'cacheSeconds':3600,'minObjectBytes':1}
        atomic_json(self.data/'archive-policy.json',self.policy)
        self.cold=ColdArchive(self.data);self.objects=Objects(self.data);self.library=EvidenceLibrary(self.store,self.data)
        self.output=self.data/'trials'/'launch';self.raw=self.output/'harbor/t/artifacts/qsim_logs/public_job_results/results/job.json'
        self.raw.parent.mkdir(parents=True);self.content=(b'{"complete scientific evidence":123}\n'*2000);self.raw.write_bytes(self.content)
        self.sha=hashlib.sha256(self.content).hexdigest()
        self.trial=self.store.put('trials',{'id':'t','campaignId':'c','state':'finished','output':str(self.output),'evidenceIndex':{'state':'complete'}})
        self.e=self.library.add('c','t','raw',self.content,{'archive':str(self.raw.relative_to(self.output))})
        self.objects.archive(self.output)
    def cycle(self):self.cold.cycle(self.store)
    def test_eviction_restoration_preserves_bytes_identity_and_official_metadata(self):
        before=self.store.run('t');self.cycle()
        self.assertFalse(self.raw.exists());self.assertFalse(self.objects.path(self.sha).exists())
        self.assertEqual(self.store.run('t'),before)
        self.assertEqual(self.library.read('c',self.e['id'])['text'],self.content.decode()[:16000])
        self.cold.restore_tree(self.output)
        self.assertEqual(self.raw.read_bytes(),self.content)
        self.assertTrue(os.path.samefile(self.raw,self.objects.path(self.sha)))
        self.cycle();self.assertTrue(self.raw.exists(),'recently restored evidence stays cached')
    def test_active_published_view_pins_all_aliases(self):
        self.store.put('campaigns',{'id':'c','state':'running','config':{'storagePolicy':'shared-artifacts-v1'}})
        service=SimpleNamespace(data=self.data,store=self.store)
        view=FileViews(service).evidence('c',self.e)
        self.cycle()
        self.assertTrue(self.raw.exists());self.assertTrue((self.data/'campaigns/c/meta-files'/view['path'].lstrip('/')).exists())
        self.assertGreater(self.cold.snapshot()['storedBytes'],0)
    def test_closed_view_is_restored_for_native_session_paths(self):
        service=SimpleNamespace(data=self.data,store=self.store)
        view=FileViews(service).evidence('c',self.e);target=self.data/'campaigns/c/meta-files'/view['path'].lstrip('/')
        self.cycle();self.assertFalse(target.exists())
        self.cold.restore_tree(target.parent)
        self.assertEqual(target.read_bytes(),self.content)
        self.assertEqual(FileViews(service).evidence('c',self.e)['sha256'],self.sha)
    def test_running_and_unindexed_trials_are_not_copied(self):
        for state,index in [('running','complete'),('finished','running')]:
            self.store.put('trials',{**self.trial,'state':state,'evidenceIndex':{'state':index}})
            self.cycle();self.assertTrue(self.raw.exists());self.assertEqual(self.cold.snapshot().get('objectCount',0),0)
    def test_bad_remote_copy_does_not_delete_original(self):
        with patch.object(self.cold,'_verify_remote',side_effect=ValueError('bad copy')):
            with self.assertRaisesRegex(ValueError,'bad copy'):self.cycle()
        self.assertEqual(self.raw.read_bytes(),self.content)
        self.assertFalse(list(self.remote.rglob('*.gz')))
    def test_corruption_and_missing_remote_never_publish_partial_restore(self):
        self.cycle();remote=next(self.remote.rglob('*.gz'))
        remote.write_bytes(gzip.compress(b'wrong'))
        with self.assertRaises(ValueError):self.library.read('c',self.e['id'])
        self.assertFalse(self.objects.path(self.sha).exists())
        remote.unlink()
        with self.assertRaises(FileNotFoundError):self.library.read('c',self.e['id'])
    def test_unknown_hardlink_keeps_local_body_and_budget_failure_keeps_source(self):
        external=Path(self.tmp.name)/'external';os.link(self.raw,external)
        self.cycle();self.assertTrue(self.raw.exists())
        external.unlink();self.cold.policy['maxBytes']=1
        # Already verified objects can still be retained; new uploads obey budget.
        body=Objects(self.data).put(b'another');sha=body.name
        with self.assertRaisesRegex(OSError,'budget'):self.cold.publish(sha,[],['c'])
        self.assertTrue(body.exists())
    def test_deletion_retains_cross_campaign_body_and_last_owner_removes_remote(self):
        self.store.put('campaigns',{'id':'other','state':'finished','config':{}})
        other=self.library.add('other',None,'raw',self.content,{'archive':'shared.json'})
        self.cycle();remote=next(self.remote.rglob('*.gz'))
        self.cold.delete_campaign('c',self.store);self.assertTrue(remote.exists())
        with self.store.connection(True) as db:db.execute('DELETE FROM evidence WHERE campaign=?',('c',))
        self.cold.delete_campaign('other',self.store);self.assertFalse(remote.exists())
    def test_locator_reopens_and_traversal_is_rejected(self):
        self.cycle();self.assertEqual(ColdArchive(self.data).read(self.sha),self.content)
        with self.assertRaises(ValueError):self.cold.safe('../outside')
        link=self.data/'alias';link.symlink_to(self.remote,target_is_directory=True)
        with self.assertRaises(ValueError):self.cold.safe('alias/file')

    def test_remote_receipt_failure_keeps_local_and_retry_finishes(self):
        with patch.object(self.cold,'receipt',side_effect=OSError('remote full')):
            with self.assertRaisesRegex(OSError,'remote full'):self.cycle()
        self.assertEqual(self.raw.read_bytes(),self.content)
        self.cycle();self.assertFalse(self.raw.exists())
        receipt=json.loads(next(self.remote.rglob('*.json')).read_text())
        self.assertEqual(receipt['body']['sha'],self.sha)
        self.assertEqual(receipt['owners'],['c'])
        self.assertEqual(receipt['aliases'][0]['path'],self.raw.relative_to(self.data).as_posix())

    def test_blocked_network_restore_has_bounded_wait(self):
        self.cycle();remote=next(self.remote.rglob('*.gz'));remote.unlink();os.mkfifo(remote)
        self.cold.policy['restoreTimeoutSeconds']=0.2
        start=time.monotonic()
        with self.assertRaisesRegex(TimeoutError,'timed out'):self.cold.materialize(self.sha)
        self.assertLess(time.monotonic()-start,2)
        self.assertFalse(self.objects.path(self.sha).exists())

    def test_busy_object_does_not_block_other_evidence_or_status(self):
        self.cold.policy['lockTimeoutSeconds']=0.1
        with self.cold.lock(self.sha):
            start=time.monotonic()
            with self.assertRaises(TimeoutError):self.cold.read(self.sha)
            self.assertLess(time.monotonic()-start,1)
            self.assertTrue(self.cold.snapshot()['enabled'])
            other=self.objects.put(b'other')
            self.assertEqual(self.cold.read(other.name),b'other')

    def test_remote_parent_symlink_is_rejected_before_eviction(self):
        (self.remote/'test').symlink_to(self.data,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):self.cycle()
        self.assertEqual(self.raw.read_bytes(),self.content)

    def test_reference_preparation_restores_only_allowed_evidence_before_writes(self):
        self.cycle();self.assertFalse(self.objects.path(self.sha).exists())
        payload={'alternatives':[{'evidenceRefs':[self.e['id']]}]}
        self.cold.prepare_references(self.store,'unrelated',payload)
        self.assertFalse(self.objects.path(self.sha).exists())
        self.cold.prepare_references(self.store,'c',payload)
        with self.store.connection(True):
            self.assertEqual(self.objects.path(self.sha).read_bytes(),self.content)
        self.cycle();self.assertTrue(self.objects.path(self.sha).exists())
