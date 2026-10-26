import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.execution.host.storage_layout import state_path, lock_path, runtime_cache, task_storage
from src.evidence.objects import Objects
from src.evidence.cold import ColdArchive
from src.control.store import Store
from src.control.storage import Storage
from src.execution.bundle.freeze import _object


class DeploymentStorageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.data = self.root/'persistent'
        self.data.mkdir()
        self.profile = {'version':'nfs-primary-v1','persistentRoot':str(self.data),
            **{name:str(self.root/name) for name in ('stateRoot','cacheRoot','scratchRoot','containerRoot')}}
        config = self.root/'profile.json'
        config.write_text(json.dumps(self.profile))
        env = patch.dict(os.environ, {'PHYEXP_DEPLOYMENT_PROFILE':str(config)})
        env.start();self.addCleanup(env.stop)

    def test_live_databases_and_locks_stay_outside_persistent_root(self):
        store = Store(self.data/'control.sqlite')
        cold = ColdArchive(self.data)
        with cold.db(): pass
        self.assertFalse((self.data/'control.sqlite').exists())
        self.assertFalse((self.data/'archive-index.sqlite').exists())
        self.assertEqual(store.path, self.root/'stateRoot/control.sqlite')
        self.assertEqual(cold.index, self.root/'stateRoot/archive-index.sqlite')
        a = lock_path(self.data/'campaigns/a/start.lock')
        self.assertTrue(a.is_relative_to(self.root/'stateRoot'))
        self.assertEqual(a,lock_path(self.data/'campaigns/a/start.lock'))
        self.assertNotEqual(a,lock_path(self.data/'campaigns/b/start.lock'))

    def test_reports_stay_readable_with_database_on_another_root(self):
        store=Store(self.data/'control.sqlite')
        body=json.dumps({'id':'report-one','campaignId':'campaign-one','markdown':'durable report'}).encode()
        report=self.data/'reports/report-one/report.json';report.parent.mkdir(parents=True);report.write_bytes(body)
        with store.connection(True) as db:
            db.execute('INSERT INTO reports VALUES(?,?,?)',('report-one','campaign-one',json.dumps({'id':'report-one','reportRef':{'sha256':hashlib.sha256(body).hexdigest()}})))
        self.assertEqual(store.get('reports','report-one')['markdown'],'durable report')
        self.assertEqual(store.data,self.data)

    def test_nonmanaged_instances_keep_original_paths(self):
        path=self.root/'other/control.sqlite'
        self.assertEqual(state_path(path),path)
        self.assertEqual(runtime_cache(path),path)
        self.assertEqual(task_storage(self.root/'other'),{})

    def test_current_meta_closeout_uses_split_state_and_persistent_roots(self):
        from src.control.service import ControlService
        from src.control.meta import MetaDriver
        from src.control.meta_native_composition import freeze
        from src.control.stop_policy import META_POLICY
        root=Path(__file__).resolve().parents[2]
        service=ControlService(root,self.data,root.parent/'Quantum-Harbor','http://127.0.0.1:1')
        self.addCleanup(service.pool.shutdown,wait=True)
        model={'provider':'openai-codex','model':'gpt-6-luna','reasoningEffort':'medium'}
        c=service.store.create({'solver':model,'meta':model,'tasks':['time_budgeted_hamlearn_10q'],
            'concurrency':1,'wallTimeSeconds':7200,'stopPolicy':META_POLICY,'objective':'解释已有结果'},'fixture')
        with patch('src.control.meta_native_composition.prepare_image',return_value='sha256:'+'a'*64):
            c['config']['metaComposition']=freeze(root,self.data,c['config'])
        service.store.put('campaigns',c);service.store.control(c['id'],'start','start')
        result=service.meta_api.call(c['id'],'campaign_finish',{'reason':'无需新增实验','summary':'保留已有证据与限制','idempotencyKey':'finish'})
        self.assertEqual(result['state'],'closing')
        driver=MetaDriver(service)
        with patch.object(driver,'start',side_effect=AssertionError('Closeout must not restart Meta')):
            driver.tick(c['id'])
        self.assertEqual(service.store.status(c['id'])['state'],'finished')
        self.assertEqual(service.store.path,self.root/'stateRoot/control.sqlite')
        self.assertFalse((self.data/'control.sqlite').exists())

    def test_closed_body_is_shared_without_copy_and_corruption_is_rejected(self):
        source=self.data/'output';source.write_bytes(b'original result'*1000)
        inode=source.stat().st_ino
        objects=Objects(self.data);row=objects.share(source)
        self.assertEqual(source.stat().st_ino,inode)
        self.assertTrue(os.path.samefile(source,objects.path(row['sha256'])))
        copy=self.data/'second';copy.write_bytes(source.read_bytes())
        objects.share(copy)
        self.assertTrue(os.path.samefile(source,copy))
        bad=self.data/'bad';bad.write_bytes(b'wrong')
        with self.assertRaises(ValueError): objects.share(bad,row['sha256'])

    def test_build_object_uses_same_durable_inode(self):
        artifact=self.data/'candidate.tar';artifact.write_bytes(b'build artifact')
        store=self.data/'objects';store.mkdir()
        identity,descriptor=_object(store,'harness-artifact',{'candidate.tar':artifact})
        target=store/identity/'assets/candidate.tar'
        self.assertTrue(os.path.samefile(artifact,target))
        self.assertEqual(descriptor['files']['candidate.tar'],hashlib.sha256(target.read_bytes()).hexdigest())

    def test_mounts_preserve_public_private_boundary_and_trial_isolation(self):
        first=task_storage(self.data/'trials/one')
        second=task_storage(self.data/'trials/two')
        public=[m for m in first['main']['volumes'] if m['target']=='/qsim_logs/public_job_results'][0]
        private=[m for m in first['qsim']['volumes'] if m['target']=='/qsim_logs'][0]
        self.assertTrue(public['read_only'])
        self.assertNotIn(private['source'],[m['source'] for m in first['main']['volumes']])
        self.assertTrue(set(m['source'] for m in first['main']['volumes']).isdisjoint(m['source'] for m in second['main']['volumes']))
        self.assertEqual(task_storage(self.data/'trials/one',verifier=True),{})
        output=[m for m in first['main']['volumes'] if m['target']=='/tmp/phyexp-output'][0]
        self.assertEqual(Path(output['source']),self.data/'trials/one/phyexp/candidate-output')

    def test_escaping_state_path_is_rejected(self):
        with self.assertRaises(ValueError): state_path(self.data/'../outside.sqlite')

    def test_idle_probe_warms_admission_and_stalled_probe_does_not_stop_activity(self):
        store=Store(self.data/'control.sqlite')
        storage=Storage(SimpleNamespace(data=self.data,store=store))
        storage.last_maintenance=time.time()
        entered=threading.Event();release=threading.Event()
        def disk_read():
            entered.set();release.wait(5)
            return [{'label':'data','free':100*1024**3,'total':200*1024**3,'freeInodes':100000}]
        with patch.object(storage,'_read_disks',side_effect=disk_read),patch.object(storage.archive,'schedule'):
            try:
                storage.schedule()
                self.assertTrue(entered.wait(1))
                pressure=storage.pressure()
                self.assertTrue(pressure['waiting'])
                self.assertFalse(pressure['critical'])
                self.assertTrue(pressure['disks'][0]['pending'])
            finally:
                release.set();storage.disk_probe.join(2)
            self.assertFalse(storage.pressure()['waiting'])


if __name__=='__main__': unittest.main()
