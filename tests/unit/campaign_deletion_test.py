"""Deletion against isolated persistence, real local processes and fake engine facts."""
import asyncio
import fcntl
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse
from src.control.service import ControlService
from src.control.server import make_app
from src.control.store import TABLES, Conflict, Refused
from src.control.deletion_runtime import engine_inventory
from src.control.deletion_storage import Inventory, remove_path
from src.evidence.objects import Objects, POLICY
from src.execution.bundle.freeze import freeze
from src.execution.bundle.manifest import verify, canonical, digest
from src.execution.bundle.project import freeze_project, source_tar
from src.exporting.project import export_project

ROOT=Path(__file__).resolve().parents[2]


class CampaignDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='phyexp deletion ')
        self.data=Path(self.temp.name)
        self.services=[];self.processes=[]
        self.service=self.new_service();self.store=self.service.store
        model={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
        self.config={'name':'待删除的合成活动','solver':model,'meta':model,'tasks':['time_budgeted_hamlearn_10q'],
                     'wallTimeSeconds':7200,'concurrency':1,'maxTrials':4,'maxRounds':4}
        self.c=self.store.create(self.config,'create')['id']
        self.client=TestClient(make_app(self.service,supervise=False))
        self.client.headers['Authorization']='Bearer '+self.service.user_token

    def new_service(self):
        service=ControlService(ROOT,self.data,ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
        self.services.append(service);return service

    def tearDown(self):
        for service in self.services:
            service.pool.shutdown(wait=True)
            for worker in (service.deletions.worker,service.storage.worker):
                if worker:worker.join(5)
        for process in self.processes:
            if process.poll() is None:process.kill()
            process.wait(timeout=5)
        self.client.close();self.temp.cleanup()

    def file(self,relative,content='history'):
        p=self.data/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content);return p

    def request(self,campaign=None,key='delete',**args):
        campaign=campaign or self.c
        preview=self.service.deletions.preview(campaign)
        return self.service.deletions.request(campaign,preview.get('expectedRevision'),key,**args)

    def finish(self,campaign=None,service=None):
        service=service or self.service;campaign=campaign or self.c
        service.deletions.advance(campaign)
        self.assertEqual(service.store.deletion(campaign)['state'],'deleted',service.store.deletion(campaign))

    def test_complete_scope_includes_every_table_files_and_global_create_receipt(self):
        evidence=self.service.evidence.add(self.c,None,'trace','private history',{})
        self.file('campaigns/'+self.c+'/meta-sessions/main/events.json','private session')
        for table in TABLES:
            if table in ('campaigns','evidence','candidates','owned_artifacts'):continue
            row={'id':table+'-owned','campaignId':self.c,'state':'finished'}
            if table in ('trials','reference_runs'):
                row.update(launchId=table+'-launch',output=str(self.file('trials/'+table+'-launch/trace.json').parent))
                self.file('trials/'+table+'-launch.supervisor.log')
            elif table=='reports':row.update(markdownPath=str(self.file('reports/'+row['id']+'/report.md')))
            elif table=='exports':
                row.update(path=str(self.file('exports/'+row['id']+'/harness/plugin.mjs').parent),
                           archive=str(self.file('exports/'+row['id']+'/harness.zip')),
                           validationEvidence=str(self.file('export-checks/owned/validation.json',json.dumps({'exportId':row['id']}))))
            elif table=='source_adoptions':row.update(sha256=evidence['sha256'],source={'sourceCampaignId':'historical-other'})
            self.store.put(table,row)
        self.file('result-recoveries/recovery',json.dumps({'campaignId':self.c,'before':{'history':'private'}}))
        global_log=self.file('supervisor-errors.jsonl',json.dumps({'error':self.c})+'\n'+json.dumps({'error':'platform-only'})+'\n')
        other=self.store.create({**self.config,'name':'保留活动'},'keep')
        self.request();self.finish()
        for table in TABLES:self.assertEqual(self.store.list(table,self.c),[],table)
        self.assertEqual(self.store.events(self.c),[])
        self.assertFalse((self.data/'campaigns'/self.c).exists())
        for name in ('trials','reports','exports','export-checks','result-recoveries','evidence'):
            self.assertFalse(any(p.is_file() for p in (self.data/name).rglob('*')),name)
        self.assertEqual(json.loads(global_log.read_text()),{'error':'platform-only'})
        self.assertEqual(self.store.get('campaigns',other['id']),other)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM commands WHERE campaign='global' AND key='create'").fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM deleted_create_keys').fetchone()[0],1)
        self.assertEqual(self.store.deletion(self.c),{'campaignId':self.c,'state':'deleted','phase':'done'})
        self.assertEqual(self.client.get('/campaigns/'+self.c).status_code,404)
        self.assertEqual(self.client.get('/evidence/'+evidence['id']).status_code,404)

    def test_http_download_remains_admitted_until_its_body_is_consumed(self):
        app=make_app(self.service,supervise=False)
        history=self.file('campaigns/'+self.c+'/history.txt')
        async def exercise():
            started=asyncio.Event();release=asyncio.Event();received=False
            @app.get('/download-fixture')
            async def download():
                async def chunks():
                    yield b'first'
                    await release.wait()
                    yield history.read_bytes()
                return StreamingResponse(chunks())
            async def receive():
                nonlocal received
                if not received:
                    received=True
                    return {'type':'http.request','body':b'','more_body':False}
                await asyncio.Event().wait()
            async def send(message):
                if message['type']=='http.response.body' and message.get('body'):started.set()
            scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1',
                   'method':'GET','scheme':'http','path':'/download-fixture','root_path':'','query_string':b'',
                   'headers':[(b'authorization',('Bearer '+self.service.user_token).encode())],
                   'server':('localhost',80),'client':('localhost',1)}
            request=asyncio.create_task(app(scope,receive,send))
            try:
                await asyncio.wait_for(started.wait(),3)
                self.request();self.service.deletions.advance(self.c)
                self.assertGreater(self.service.access.readers,0)
                self.assertTrue(history.exists())
            finally:
                release.set();await asyncio.wait_for(request,3)
        asyncio.run(exercise())
        self.assertEqual(self.service.access.readers,0)
        self.finish();self.assertFalse(history.exists())

    def test_shared_execution_objects_remain_resolvable_and_exportable_then_reclaimed(self):
        other=self.store.create(self.config,'second')['id']
        bundle=freeze(ROOT,self.data/'objects/sha256',json.loads((ROOT/'recipes/h0-sol.json').read_text()),[])
        for campaign in (self.c,other):self.store.candidate(campaign,bundle,'fixture',check={'status':'passed'})
        a=self.service.evidence.add(self.c,None,'trace','same content',{})
        b=self.service.evidence.add(other,None,'trace','same content',{})
        self.request();self.finish()
        self.assertEqual(verify(bundle['path'])['id'],bundle['id'])
        exported=export_project(bundle['path'],self.data/'external-test-output')
        self.assertEqual(verify(exported['path'])['id'],bundle['id'])
        self.assertEqual(Path(b['path']).read_text(),'same content')
        self.request(other,key='second-delete');self.finish(other)
        self.assertFalse(Path(a['path']).exists())
        self.assertFalse(any((self.data/'objects/sha256').iterdir()))

    def test_remaining_reference_check_ignores_unrelated_bodies_but_preserves_shared_history(self):
        other=self.store.create(self.config,'many-other-evidence')['id']
        own=self.service.evidence.add(self.c,None,'trace','shared history',{})
        shared=self.service.evidence.add(other,None,'trace','shared history',{})
        unrelated=[self.service.evidence.add(other,None,'trace',f'unrelated {i}',{}) for i in range(100)]
        with self.store.connection() as db:
            inventory=Inventory(self.service,self.c,db)
            with patch.object(inventory,'checked',wraps=inventory.checked) as checked:
                plan=inventory.build()
            paths={str(call.args[0]) for call in checked.call_args_list}
        self.assertEqual(plan['blockers'],[])
        self.assertTrue(all(row['path'] not in paths for row in unrelated))
        self.request();self.finish()
        self.assertEqual(Path(shared['path']).read_text(),'shared history')
        self.assertTrue(all(Path(row['path']).exists() for row in unrelated))

    def test_unrelated_evidence_symlinks_still_block_unsafe_inventory(self):
        other=self.store.create(self.config,'linked-evidence')['id']
        own=self.service.evidence.add(self.c,None,'trace','owned history',{})
        row=self.service.evidence.add(other,None,'trace','unrelated history',{})
        path=Path(row['path']);path.unlink();path.symlink_to(own['path'])
        preview=self.service.deletions.preview(self.c)
        self.assertTrue(any('符号链接' in item['message'] for item in preview['blockers']))
        self.assertTrue(Path(own['path']).exists())

    def test_v3_shared_sources_artifact_and_build_cache_survive_until_last_activity(self):
        other=self.store.create(self.config,'v3-other')['id']
        legacy=self.store.create(self.config,'v2-other')['id']
        old=freeze(ROOT,self.data/'objects/sha256',json.loads((ROOT/'recipes/h0-sol.json').read_text()),[])
        self.store.candidate(legacy,old,'old fixture',check={'status':'passed'})
        project=self.data/'campaigns'/self.c/'project';project.mkdir(parents=True)
        spec={'runContract':'harbor-process-v1','entrypoint':['run.sh'],
              'build':{'image':'fixture','argv':['sh','-c','true'],'locks':[]}}
        (project/'harness.json').write_text(json.dumps(spec));(project/'run.sh').write_text('#!/bin/sh\nexit 0\n')
        cache=self.data/'cache/project-builds';cache.mkdir(parents=True)
        def built(contents,*args,**kwargs):
            inputs={'sources':{k:digest(v) for k,v in contents.items()},'image':'sha256:'+'a'*64}
            key=digest(canonical(inputs));artifact=cache/(key+'.tar');artifact.write_bytes(source_tar(contents))
            receipt={'inputs':inputs,'artifactSha256':digest(artifact.read_bytes()),'status':'passed'}
            (cache/(key+'.json')).write_text(json.dumps(receipt));(cache/(key+'.lock')).touch()
            return artifact,receipt
        bundles=[]
        with patch('src.execution.bundle.project.build',side_effect=built):
            for campaign in (self.c,other):
                b=freeze_project(ROOT,self.data/'objects/sha256',project,{'fixture':campaign},cache,io.StringIO(),{},
                    on_publish=lambda path,kind,c=campaign:self.store.track_artifact(c,path,kind))
                bundles.append(b);self.store.candidate(campaign,b,'v3 fixture',check={'status':'passed'})
        self.assertNotEqual(bundles[0]['id'],bundles[1]['id'])
        unrelated=self.file('cache/project-builds/'+'f'*64+'.tar','unrelated')
        dependency=self.file('cache/dependencies/common/keep.txt','shared installation')
        # A v3 activity must not prevent deleting an unrelated v2 activity.
        self.request(legacy);self.finish(legacy)
        self.request();self.finish()
        second=bundles[1];self.assertEqual(verify(second['path'])['id'],second['id'])
        key=digest(canonical(second['manifest']['buildReceipt']['inputs']))
        for suffix in ('.json','.tar','.lock'):self.assertTrue((cache/(key+suffix)).exists())
        self.assertEqual(verify(export_project(second['path'],self.data/'external-test-output')['path'])['id'],second['id'])
        self.request(other,key='last-v3');self.finish(other)
        for suffix in ('.json','.tar','.lock'):self.assertFalse((cache/(key+suffix)).exists())
        self.assertFalse(any((self.data/'objects/sha256').iterdir()))
        self.assertTrue(unrelated.exists());self.assertTrue(dependency.exists())

    def test_legacy_v1_and_all_activity_states_can_be_deleted(self):
        old=freeze(ROOT,self.data/'objects/sha256',json.loads((ROOT/'recipes/h0-sol.json').read_text()),[],legacy=True)
        self.store.candidate(self.c,old,'v1 fixture',check={'status':'passed'})
        self.request();self.finish();self.assertFalse(Path(old['path']).exists())
        for state in ('draft','running','paused','closing','finished','failed'):
            with self.subTest(state=state):
                c=self.store.create(self.config,'state-'+state);c['state']=state;self.store.put('campaigns',c)
                preview=self.service.deletions.preview(c['id'])
                self.assertEqual(preview['blockers'],[])
                self.assertEqual(preview['requiresStop'],state not in ('draft','finished','failed'))
                self.request(c['id'],key=state);self.finish(c['id'])

    def test_inventory_excludes_large_bodies_and_revalidates_links_before_removal(self):
        self.store.put('reports',{'id':'large','campaignId':self.c,'body':'body must not be loaded'*10000})
        file=self.file('campaigns/'+self.c+'/history')
        with self.store.connection() as db:
            inventory=Inventory(self.service,self.c,db)
            self.assertNotIn('body',inventory.rows['reports'][0])
            self.assertFalse(inventory.build()['blockers'])
        self.request();directory=file.parent
        file.unlink();directory.rmdir();directory.symlink_to(self.data/'reports',target_is_directory=True)
        self.service.deletions.advance(self.c)
        self.assertEqual(self.store.deletion(self.c)['state'],'failed')
        self.assertIn('符号链接',self.store.deletion(self.c)['error'])

    def test_failed_build_staging_and_only_its_labeled_container_are_cleaned(self):
        stage=self.file('cache/project-builds/tmp-fixture/source.tar','private source').parent
        self.store.track_artifact(self.c,stage,'project_build_temp')
        artifact=self.file('cache/project-builds/'+'c'*64+'.tar','private artifact')
        self.store.track_artifact(self.c,artifact,'project_build')
        containers=[{'Id':'owned','Config':{'Labels':{'phyexp.build.stage':str(stage)}}},
                    {'Id':'unrelated','Config':{'Labels':{'phyexp.build.stage':str(stage)+'-other'}}}]
        calls=[]
        def engine(*args):
            calls.append(args)
            if args==('ps','-aq'):return 'owned unrelated'
            if args[0]=='inspect':return json.dumps(containers)
            return ''
        self.request()
        with patch('src.control.deletion_runtime.docker',side_effect=engine):self.finish()
        self.assertIn(('rm','-f','-v','owned'),calls)
        self.assertFalse(stage.exists());self.assertFalse(artifact.exists())

    def test_engine_inventory_tolerates_unrelated_resource_removal_but_not_engine_failure(self):
        for kind in ('container','network','volume'):
            with self.subTest(kind=kind):
                with patch('src.control.deletion_runtime.docker',side_effect=[
                    'owned transient',Refused('transient disappeared'),'owned',json.dumps([{'Id':'owned'}])]):
                    self.assertEqual(engine_inventory(kind),[{'Id':'owned'}])
                with patch('src.control.deletion_runtime.docker',side_effect=['owned',Refused('engine unavailable'),'owned']):
                    with self.assertRaisesRegex(Refused,'engine unavailable'):engine_inventory(kind)

    def test_unknown_hardlink_cannot_be_silently_left_after_success(self):
        body=Objects(self.data).put(b'private history')
        owned=self.data/'campaigns'/self.c/'view';owned.parent.mkdir(parents=True);os.link(body,owned)
        unknown=self.data/'unknown-view';os.link(body,unknown)
        self.request();self.service.deletions.advance(self.c)
        self.assertEqual(self.store.deletion(self.c)['state'],'failed')
        self.assertIn('未登记',self.store.deletion(self.c)['error'])
        self.assertTrue(unknown.exists());self.assertTrue(body.exists())
        unknown.unlink();self.service.deletions.request(self.c,None,'retry-links',True);self.finish()

    def test_busy_build_cache_is_not_removed_and_can_be_retried(self):
        paths=[self.file('cache/project-builds/'+'d'*64+suffix) for suffix in ('.tar','.json','.lock')]
        for path in paths:self.store.track_artifact(self.c,path,'project_build')
        self.request()
        with paths[-1].open() as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.service.deletions.advance(self.c)
            self.assertEqual(self.store.deletion(self.c)['state'],'failed')
            self.assertIn('缓存仍在使用',self.store.deletion(self.c)['error'])
            self.assertTrue(all(p.exists() for p in paths))
        self.service.deletions.request(self.c,None,'retry-build',True);self.finish()
        self.assertFalse(any(p.exists() for p in paths))

    def test_build_crash_registers_cache_and_staging_before_writing_sources(self):
        script='''
import io,os,subprocess,sys,types
from pathlib import Path
from src.control.store import Store
from src.execution.bundle.project import build
data,campaign=Path(sys.argv[1]),sys.argv[2];store=Store(data/'control.sqlite');write=Path.write_bytes
subprocess.run=lambda *a,**k:types.SimpleNamespace(returncode=0,stdout='sha256:'+'a'*64)
def crash(path,content):
    result=write(path,content)
    if path.name=='source.tar':os._exit(91)
    return result
Path.write_bytes=crash
build({'run.sh':b'exit 0'}, {'build':{'image':'fixture','argv':['sh','-c','true']}},
      data/'cache/project-builds',io.StringIO(),{},on_publish=lambda p,k:store.track_artifact(campaign,p,k))
'''
        result=subprocess.run([sys.executable,'-c',script,str(self.data),self.c],cwd=ROOT,timeout=10)
        self.assertEqual(result.returncode,91)
        rows=self.store.list('owned_artifacts',self.c)
        self.assertEqual(sum(r['kind']=='project_build' for r in rows),3)
        stage=Path(next(r['path'] for r in rows if r['kind']=='project_build_temp'))
        self.assertTrue((stage/'source.tar').exists())
        self.request()
        with patch('src.control.deletion_runtime.docker',return_value=''):self.finish()
        self.assertFalse(any((self.data/'cache/project-builds').iterdir()))

    def test_native_archive_and_file_view_hardlinks_are_collected_only_on_last_reference(self):
        for id in (self.c,):
            row=self.store.get('campaigns',id);row['config']['storagePolicy']=POLICY;self.store.put('campaigns',row)
        other=self.store.create({**self.config,'storagePolicy':POLICY},'shared')['id']
        objects=Objects(self.data);body=objects.put(b'shared history')
        for campaign in (self.c,other):
            view=self.data/'campaigns'/campaign/'meta-files/materials/view.txt';view.parent.mkdir(parents=True)
            os.link(body,view)
        e=self.service.evidence.add(self.c,None,'trace','unique history',{})
        archive=self.file('trials/archive/history.json','archive-only');objects.archive(archive.parent)
        archive_body=objects.path(hashlib.sha256(b'archive-only').hexdigest())
        self.store.put('trials',{'id':'archived','campaignId':self.c,'state':'finished','output':str(archive.parent),'launchId':'archive'})
        self.request();self.finish()
        self.assertTrue(body.exists());self.assertFalse(archive_body.exists());self.assertFalse(Path(e['path']).exists())
        self.request(other,key='last');self.finish(other);self.assertFalse(body.exists())

    def test_shared_meta_composition_and_runtime_follow_remaining_campaign(self):
        other=self.store.create(self.config,'second')['id'];sha='a'*64;composition='b'*64
        body=self.file('meta-objects/sha256/'+sha,'meta source')
        root=self.file('meta-compositions/'+composition+'/manifest.json',json.dumps({'version':'meta-composition-v2','files':{'runtime.mjs':sha}})).parent
        runtime=self.file('cache/meta-runtimes/'+composition+'/runtime.mjs','meta source').parent
        for campaign in (self.c,other):
            c=self.store.get('campaigns',campaign);c['config']['metaComposition']={'id':composition};self.store.put('campaigns',c)
        self.request();self.finish();self.assertTrue(body.exists());self.assertTrue(runtime.exists())
        self.request(other,key='last');self.finish(other)
        self.assertFalse(body.exists());self.assertFalse(root.exists());self.assertFalse(runtime.exists())

    def test_cross_campaign_user_only_and_meta_adoptions_block_deletion(self):
        e=self.service.evidence.add(self.c,None,'trace','origin',{})
        other=self.store.create(self.config,'other')['id']
        for scope in ('user-only','meta-research'):
            self.service.adoptions.adopt(other,self.c,'evidence',e['id'],'test dependency',scope,scope)
        preview=self.service.deletions.preview(self.c)
        self.assertEqual(len(preview['blockers']),2)
        self.assertEqual({x['campaignId'] for x in preview['blockers']},{other})
        with self.assertRaises(Conflict):self.request()
        self.assertIsNone(self.store.deletion(self.c));self.assertTrue(Path(e['path']).exists())

    def test_user_authority_revision_and_duplicate_request(self):
        route='/campaigns/'+self.c+'/deletion'
        revision=self.store.get('campaigns',self.c)['revision']
        _,token=self.service.lease(self.c,'meta',time.time()+60)
        with TestClient(make_app(self.service,supervise=False)) as client:
            client.headers['Authorization']='Bearer '+token
            self.assertEqual(client.get(route).status_code,403)
            self.assertEqual(client.post(route,json={'expectedRevision':revision,'idempotencyKey':'unauthorized'}).status_code,403)
        self.assertEqual(self.client.post(route,json={'expectedRevision':revision-1,'idempotencyKey':'stale'}).status_code,409)
        first=self.client.post(route,json={'expectedRevision':revision,'idempotencyKey':'valid'})
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(self.client.post(route,json={'expectedRevision':revision,'idempotencyKey':'valid'}).json(),first.json())
        self.assertEqual(self.client.post('/campaigns/'+self.c+'/control',json={'action':'start','idempotencyKey':'late'}).status_code,409)
        self.assertEqual(self.client.get('/campaigns/'+self.c).json()['deletion']['phase'],'stopping')
        self.finish()
        self.assertEqual(self.client.get(route).json()['state'],'deleted')
        self.assertEqual(self.client.post(route,json={'expectedRevision':revision,'idempotencyKey':'valid'}).json()['state'],'deleted')

    def test_late_callbacks_and_old_create_replay_cannot_resurrect_activity(self):
        c=self.store.get('campaigns',self.c);self.request()
        with self.assertRaises(Conflict):self.store.put('campaigns',c)
        with self.assertRaises(Conflict):self.service.evidence.add(self.c,None,'late','late bytes',{})
        with self.assertRaises(Conflict):self.service.workspace(self.c)
        other=self.store.create(self.config,'other')['id']
        with self.assertRaises(Conflict):self.service.adoptions.adopt(other,self.c,'report','missing','reason','user-only','late')
        self.finish()
        with self.assertRaises(Conflict):self.store.create(self.config,'create')
        with self.assertRaises(Conflict):self.service.create(self.config,'create')
        with self.assertRaises(Conflict):self.store.put('trials',{'id':'late','campaignId':self.c,'state':'finished'})
        self.assertFalse((self.data/'campaigns'/self.c).exists())

    def test_partial_failure_restart_and_retry_preserve_recovery_plan(self):
        self.file('campaigns/'+self.c+'/workspace/history.txt')
        e=self.service.evidence.add(self.c,None,'trace','original',{})
        self.request();removed=[]
        def fail(data,path):
            if removed:raise PermissionError('synthetic filesystem failure')
            remove_path(data,path);removed.append(path)
        with patch('src.control.deletion.remove_path',side_effect=fail):self.service.deletions.advance(self.c)
        job=self.store.deletion(self.c)
        self.assertEqual(job['state'],'failed');self.assertEqual(job['phase'],'cleaning')
        self.assertTrue(job['plan']);self.assertEqual(self.store.get('campaigns',self.c)['state'],'deleting')
        other=self.new_service()
        self.assertEqual(other.deletions.preview(self.c)['state'],'failed')
        other.deletions.request(self.c,None,'retry',True)
        self.finish(service=other)
        self.assertFalse(Path(e['path']).exists())

    def test_admitted_operation_is_drained_and_its_failed_output_is_tracked(self):
        entered=threading.Event();release=threading.Event()
        def work():
            entered.set();release.wait(5)
            path=self.data/'export-checks/late-check'
            self.store.track_artifact(self.c,path,'export_check')
            self.file('export-checks/late-check/failed.log')
            raise RuntimeError('failed validation')
        result=self.service._operation(self.c,'test',{},work)
        self.assertTrue(entered.wait(2))
        self.request();self.service.deletions.advance(self.c)
        self.assertEqual(self.store.deletion(self.c)['phase'],'stopping')
        release.set();self.service.operations[result['operationId']].result(timeout=3)
        self.finish();self.assertFalse((self.data/'export-checks/late-check').exists())

    def test_process_crash_during_freeze_leaves_owned_staging_that_is_deleted(self):
        script='''
import json,os,sys
from pathlib import Path
from src.control.store import Store
from src.execution.bundle.freeze import freeze
root,data,campaign=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
store=Store(data/'control.sqlite');write=Path.write_bytes
def crash(path,content):
    result=write(path,content)
    if '.publishing-' in str(path):os._exit(91)
    return result
Path.write_bytes=crash
freeze(root,data/'objects/sha256',json.loads((root/'recipes/h0-sol.json').read_text()),[],
       on_publish=lambda path,kind:store.track_artifact(campaign,path,kind))
'''
        result=subprocess.run([sys.executable,'-c',script,str(ROOT),str(self.data),self.c],cwd=ROOT,timeout=10)
        self.assertEqual(result.returncode,91)
        self.assertTrue(list((self.data/'objects/sha256').glob('.publishing-*/*/object.json')))
        self.request();self.finish()
        self.assertFalse(any((self.data/'objects/sha256').iterdir()))

    def test_accepted_http_or_background_reader_delays_unlink(self):
        path=self.file('campaigns/'+self.c+'/work.txt');self.request()
        with self.service.access.enter():
            self.service.deletions.advance(self.c)
            self.assertTrue(path.exists());self.assertEqual(self.store.deletion(self.c)['phase'],'stopping')
        self.finish()

    def test_real_owned_process_is_stopped_reaped_and_unrelated_process_survives(self):
        output=self.file('trials/local-process/trace').parent
        process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)',str(output)],start_new_session=True)
        unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],start_new_session=True)
        self.processes.extend([process,unrelated])
        self.store.put('trials',{'id':'process','campaignId':self.c,'state':'running','launchId':'local-process','output':str(output),'pid':process.pid})
        self.service.children['process']=process
        self.request()
        with patch('src.control.deletion.cleanup_resources'):
            deadline=time.monotonic()+4
            while self.store.deletion(self.c)['state']=='running' and time.monotonic()<deadline:
                self.service.deletions.advance(self.c);time.sleep(.02)
        self.assertEqual(self.store.deletion(self.c)['state'],'deleted')
        self.assertIsNotNone(process.poll());self.assertIsNone(unrelated.poll())
        self.assertNotIn('process',self.service.children)

    def test_path_escape_symlink_and_mixed_backup_refuse_without_removing_files(self):
        outside=Path(self.temp.name).parent/'never-delete-fixture'
        self.store.put('exports',{'id':'unsafe','campaignId':self.c,'path':str(outside)})
        self.assertTrue(self.service.deletions.preview(self.c)['blockers'])
        with self.store.connection(True) as db:db.execute("DELETE FROM exports WHERE id='unsafe'")
        directory=self.data/'campaigns'/self.c;directory.parent.mkdir(exist_ok=True);directory.symlink_to(self.data)
        self.assertTrue(self.service.deletions.preview(self.c)['blockers']);directory.unlink()
        backup=self.file('history-storage/plan/control-before.sqlite','mixed snapshot')
        preview=self.service.deletions.preview(self.c)
        self.assertTrue(any(b['kind']=='mixed_backup' for b in preview['blockers']))
        with self.assertRaises(Conflict):self.request()
        self.assertTrue(backup.exists())

    def test_internal_workspace_symlink_is_unlinked_without_touching_target(self):
        target=self.file('unrelated/keep.txt','keep')
        work=self.data/'campaigns'/self.c/'workspace';work.mkdir(parents=True)
        (work/'link').symlink_to(target.parent,target_is_directory=True)
        self.request();self.finish();self.assertEqual(target.read_text(),'keep')

    def test_running_job_resumes_after_controller_restart(self):
        self.file('campaigns/'+self.c+'/state');self.request()
        service=self.new_service();service.deletions.tick();service.deletions.worker.join(5)
        self.assertEqual(service.store.deletion(self.c)['state'],'deleted')


if __name__=='__main__':unittest.main()
