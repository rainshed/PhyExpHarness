import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from src.control.plugin_library import PluginLibrary
from src.control.store import Store, Conflict, Refused
from src.control.deletion import ActivityAccess
from src.execution.bundle.project import SourceFiles


class PluginLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.data=Path(self.tmp.name)
        self.store=Store(self.data/'control.sqlite')
        self.service=SimpleNamespace(store=self.store,data=self.data,access=ActivityAccess())
        self.lib=PluginLibrary(self.service)
        self.manifest={'name':'clock','version':'1','entry':'index.mjs','assembly':{'contract':'dsh-plugin-v1','entry':'index.mjs','requires':[]}}
        self.files=SourceFiles();self.files['index.mjs']=b'export const apply = () => {};';self.files.modes={'index.mjs':0o644}

    def save(self,origin='one'):
        return self.lib.save(self.files,self.manifest,{'campaignId':origin})

    def test_published_source_recovers_after_index_transaction_interruption(self):
        from unittest.mock import patch
        original=self.lib.write
        def crash(db,row,table='plugin_library'):
            if table=='plugin_library':raise OSError('fixture interrupted before index commit')
            return original(db,row,table)
        with patch.object(self.lib,'write',side_effect=crash):
            with self.assertRaises(OSError):self.save()
        self.assertEqual(self.lib.page()['total'],0)
        recovered=PluginLibrary(self.service)
        self.assertEqual(recovered.page()['total'],1)
        self.assertIn('apply',recovered.detail(recovered.page()['items'][0]['id'],'index.mjs')['content'])
        with self.store.connection() as db:self.assertEqual(len(recovered.rows(db,'plugin_library_publications')),0)

    def test_content_dedup_sources_modes_and_deleted_tombstone(self):
        a=self.save();self.assertEqual(a,self.save('two'))
        self.assertEqual(len(self.lib.get(a)['sources']),2)
        preview=self.lib.preview(a)
        changed=self.lib.change(a,'delete',preview['versions'],'delete-once')
        self.assertEqual(changed,self.lib.change(a,'delete',preview['versions'],'delete-once'))
        self.assertEqual(self.lib.page()['total'],0)
        self.save('three');self.assertTrue(self.lib.get(a)['deleted'])
        with self.assertRaises(Conflict):self.lib.change(a,'restore',preview['versions'],'stale')
        self.lib.change(a,'restore',self.lib.preview(a)['versions'],'restore')
        self.assertEqual(self.lib.page()['total'],1)
        self.files.modes['index.mjs']=0o755
        self.assertNotEqual(self.save(),a)
        self.files['index.mjs']=b'export const apply = () => 42;'
        self.assertNotEqual(self.save(),a)

    def test_bad_description_is_a_catalog_diagnostic_but_disk_failure_propagates(self):
        from unittest.mock import patch
        files=SourceFiles();files['plugins/clock/index.mjs']=self.files['index.mjs']
        spec={'plugins':[{'name':'clock','path':'plugins/clock'}]}
        files['plugins/clock/plugin.json']=json.dumps({**self.manifest,'purpose':42}).encode()
        result=self.lib.capture(files,spec,{'campaignId':'one'})
        self.assertEqual(result['plugins'],[]);self.assertEqual(len(result['issues']),1)
        files['plugins/clock/plugin.json']=json.dumps(self.manifest).encode()
        with patch.object(self.lib,'save',side_effect=OSError('fixture disk full')):
            with self.assertRaises(OSError):self.lib.capture(files,spec,{'campaignId':'one'})

    def test_source_independent_and_integrity_checked(self):
        id=self.save()
        restarted=PluginLibrary(self.service)
        self.assertIn('apply',restarted.detail(id,'index.mjs')['content'])
        with self.assertRaises((ValueError,Refused)):restarted.detail('../control.sqlite')
        with self.assertRaises(Refused):restarted.detail(id,'../control.sqlite')
        asset=self.lib.root/id/'assets/index.mjs';asset.chmod(0o644);asset.write_text('tampered')
        with self.assertRaisesRegex(ValueError,'mismatch'):restarted.detail(id,'index.mjs')

    def test_publication_serializes_a_stale_delete_and_cleanup(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        from src.control.plugin_library import _object
        id=self.save();preview=self.lib.preview(id);other=PluginLibrary(self.service)
        entered,release=Event(),Event()
        def slow(*args):
            entered.set()
            if not release.wait(5):raise TimeoutError('fixture publication release')
            return _object(*args)
        with ThreadPoolExecutor(3) as pool,patch('src.control.plugin_library._object',side_effect=slow):
            saving=pool.submit(self.save,'two')
            self.assertTrue(entered.wait(5))
            deleting=pool.submit(other.change,id,'delete',preview['versions'],'concurrent-delete')
            cleanup=pool.submit(other.prune,self.store.clock()+1)
            release.set();self.assertEqual(saving.result(timeout=5),id)
            with self.assertRaises(Conflict):deleting.result(timeout=5)
            self.assertEqual(cleanup.result(timeout=5),0)
        self.assertFalse(self.lib.get(id)['deleted'])
        self.assertEqual(len(self.lib.get(id)['sources']),2)
        self.assertIn('apply',self.lib.detail(id,'index.mjs')['content'])

    def test_capture_has_no_config_identity_and_failure_status_is_separate(self):
        contents=SourceFiles();contents['plugins/clock/index.mjs']=self.files['index.mjs']
        contents['plugins/clock/plugin.json']=json.dumps(self.manifest).encode()
        spec={'plugins':[{'name':'clock','path':'plugins/clock','config':{'a':1}}]}
        source={'campaignId':'one','checkId':'build'}
        capture=self.lib.capture(contents,spec,source);id=capture['plugins'][0]['id']
        spec['plugins'][0]['config']={'a':2}
        self.assertEqual(id,self.lib.capture(contents,spec,source)['plugins'][0]['id'])
        self.lib.checked(capture,source,'failed',error='build failed')
        detail=self.lib.detail(id)
        self.assertEqual(detail['buildStatus'],'failed');self.assertEqual(detail['runtimeStatus'],'not_run')
        self.assertEqual(detail['effectiveness'],'not_certified')
        self.lib.checked(capture,source,'passed')
        self.assertEqual(self.lib.detail(id)['buildStatus'],'passed')
        self.assertEqual(self.lib.detail(id)['runtimeStatus'],'not_run')
        spec['plugins'].append({'name':'unknown'})
        self.assertEqual(len(self.lib.capture(contents,spec,source)['issues']),1)

    def test_group_deletion_and_revision_protection(self):
        a=self.save();self.files['index.mjs']+=b'\n';b=self.save()
        preview=self.lib.preview(a,'plugin')
        self.assertEqual(len(preview['versions']),2)
        self.lib.change(a,'delete',preview['versions'],'whole')
        self.assertTrue(self.lib.get(a)['deleted']);self.assertTrue(self.lib.get(b)['deleted'])
        with self.assertRaises(Conflict):self.lib.change(a,'restore',preview['versions'],'old')

    def test_job_is_idempotent_and_resumable(self):
        job=self.lib.rescan('same');self.assertEqual(job,self.lib.rescan('same'))
        with self.store.connection(True) as db:
            row=self.lib.job(job['jobId']);row.update(state='running',candidateIds=['deleted-candidate'])
            self.lib.write(db,row,'plugin_library_jobs')
        reopened=PluginLibrary(self.service)
        self.assertEqual(reopened.job(job['jobId'])['state'],'pending')
        done=reopened.run_job(job['jobId'])
        self.assertEqual(done['state'],'finished');self.assertEqual(done['cursor'],1)
        self.assertIn('error',done['results'][0])
        self.assertEqual(done,reopened.run_job(job['jobId']))

    def test_undeclared_assembly_is_readable_but_not_ready(self):
        self.manifest.pop('assembly');id=self.save()
        self.assertEqual(self.lib.detail(id)['compatibility']['state'],'needs_adaptation')
        self.assertIn('apply',self.lib.detail(id,'index.mjs')['content'])

    def test_prune_retains_transitive_dependencies_and_tombstones(self):
        a=self.save()
        self.manifest={**self.manifest,'name':'dependent','assembly':{**self.manifest['assembly'],'requires':[a]}}
        b=self.save()
        self.lib.change(a,'delete',self.lib.preview(a)['versions'],'delete-a')
        self.assertEqual(self.lib.prune(self.store.clock()+1),0)
        self.lib.change(b,'delete',self.lib.preview(b)['versions'],'delete-b')
        self.assertGreater(self.lib.prune(self.store.clock()+1),0)
        self.assertTrue(self.lib.get(a)['deleted'])
        self.assertEqual(self.lib.detail(a)['sourceStatus'],'reclaimed')
        self.manifest={**self.manifest,'name':'clock','assembly':{**self.manifest['assembly'],'requires':[]}}
        self.assertEqual(a,self.save())
        self.assertTrue(self.lib.get(a)['deleted'])

if __name__=='__main__':unittest.main()
