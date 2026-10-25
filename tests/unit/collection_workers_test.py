"""Persistent phases, crash windows, scoped deletion and indexed evidence."""
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from result_collection_test import ResultCollectionTests as Fixture
from src.control.collection import work
from src.control.deletion import ActivityAccess
from src.control.store import Conflict

class CollectionWorkersTests(unittest.TestCase):
    write=Fixture.write
    def setUp(self):Fixture.setUp(self)
    def job(self):
        trial=self.store.trial_update(self.trial['id'],state='running',score=None)
        return self.service.collections.enqueue(trial)
    def run_job(self,job):work(str(self.root),str(self.service.source),job['id'],job['lockPath'])
    def test_verify_releases_execution_slot_before_index_and_restart_is_idempotent(self):
        job=self.job();self.assertEqual(self.store.status(self.cid)['counts']['activeTrials'],0)
        self.assertEqual(self.store.status(self.cid)['counts']['collectingTrials'],1)
        self.run_job(job)
        trial=self.store.run(self.trial['id']);self.assertEqual(trial['score'],0)
        self.assertEqual(trial['evidenceIndex']['state'],'pending')
        self.assertEqual(self.store.get('collection_jobs',job['id'])['stage'],'index')
        self.run_job(job);before=self.store.list('evidence',self.cid)
        self.run_job(job);self.assertEqual(before,self.store.list('evidence',self.cid))
        self.assertEqual(self.store.run(trial['id'])['evidenceIndex']['state'],'complete')
    def test_crash_after_registration_before_checkpoint_preserves_ids_and_sources(self):
        job=self.job();self.run_job(job)
        from src.evidence.library import EvidenceLibrary
        original=EvidenceLibrary.add;calls=[]
        def crash(library,*args,**kwargs):
            row=original(library,*args,**kwargs);calls.append(row)
            raise RuntimeError('crash after metadata commit')
        with patch.object(EvidenceLibrary,'add',crash),self.assertRaises(RuntimeError):self.run_job(job)
        self.assertEqual(self.store.run(self.trial['id'])['score'],0)
        self.run_job(job)
        self.assertEqual(self.store.get('evidence',calls[0]['id']),calls[0])
        rows=self.store.list('evidence',self.cid)
        self.assertEqual(len(rows),len({(r['trialId'],r['kind'],r['sha256'],r['source'].get('archive')) for r in rows}))
        a=self.service.evidence.add(self.cid,self.trial['id'],'raw-artifact','same',{'archive':'a'})
        b=self.service.evidence.add(self.cid,self.trial['id'],'raw-artifact','same',{'archive':'b'})
        self.assertNotEqual(a['id'],b['id']);self.assertEqual(a['sha256'],b['sha256'])
    def test_index_failure_does_not_erase_verified_score(self):
        job=self.job();self.run_job(job)
        self.service.collections.fail(job,'index I/O failure')
        trial=self.store.run(self.trial['id'])
        self.assertEqual(trial['score'],0);self.assertEqual(trial['evidenceIndex']['state'],'failed')
    def test_active_index_does_not_consume_verification_pool(self):
        job=self.job();self.run_job(job)
        self.service.collections.tick()
        child=self.service.collections.children[job['id']]
        child.wait(timeout=10)
        self.assertEqual(self.store.get('collection_jobs',job['id'])['state'],'complete')
    def test_activity_gate_does_not_reject_other_activity(self):
        access=ActivityAccess()
        with access.exclusive('a') as acquired:
            self.assertTrue(acquired)
            with access.enter('b'):pass
            with self.assertRaises(Conflict),access.enter('a'):pass
        with access.enter('a'),access.exclusive('a') as acquired:self.assertFalse(acquired)
    def test_queries_and_admission_do_not_run_storage_scan(self):
        self.service.storage.inventory(force=True)
        with patch.object(self.service.storage,'inventory',side_effect=AssertionError('foreground scan')):
            self.service.storage.view(self.cid)
        with patch.object(self.store,'list',side_effect=AssertionError('full scan')):
            self.service.evidence.page(self.cid,trialId=self.trial['id'])
