import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.control.service import ControlService
from src.control.server import make_app
from src.control.store import Refused,Conflict
from src.control.h0 import defaults,resolve_selection,materialize
from src.execution.bundle.project import source_tar
from src.execution.bundle.manifest import digest
from tests.fixtures.benchmark_tasks import make_tasks

ROOT=Path(__file__).resolve().parents[2]
class H0CreationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        tasks=['time_budgeted_hamlearn_10q','logical_cnot_decoder_calibration']
        quantum=make_tasks(self.root/'quantum',tasks)
        self.service=ControlService(ROOT,self.root/'data',quantum,'http://127.0.0.1:1',launch_trial=lambda *_:None)
        self.addCleanup(self.service.pool.shutdown)
        model={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
        self.cfg={'name':'fixture','solver':model,'meta':model,'tasks':tasks,'concurrency':1,'wallTimeSeconds':20000,'maxTrials':1}
        self.client=TestClient(make_app(self.service,supervise=False));self.addCleanup(self.client.close)
        self.client.headers['Authorization']='Bearer '+self.service.user_token
        self.default=self.client.get('/plugin-library/h0/defaults').json()
        self.selection={k:self.default[k] for k in ('version','templateId','plugins')}
        def built(contents,spec,cache,log,resources,**kwargs):
            artifact=self.root/(digest(source_tar(contents))+'.tar');artifact.write_bytes(source_tar(contents))
            return artifact,{'artifactSha256':digest(artifact.read_bytes()),'status':'passed','inputs':{'sources':{n:digest(v) for n,v in contents.items()},'sourceModes':contents.modes}}
        for target,value in [('src.execution.bundle.project.build',built)]:
            mock=patch(target,side_effect=value);mock.start();self.addCleanup(mock.stop)
        mock=patch.object(self.service,'_operation',return_value={'operationId':'fixture'});mock.start();self.addCleanup(mock.stop)

    def create(self,selection=None,key='create'):
        cfg={**self.cfg,**({'h0Selection':selection} if selection is not None else {})}
        return self.service.create(cfg,key)

    def test_nonempty_h0_reference_is_frozen_and_does_not_force_trials(self):
        c=self.create(self.selection);cid=c['id']
        self.assertIsNone(c['startedAt']);self.assertFalse(c['candidates'])
        row=self.service.build_candidate(cid,[],'H0')
        current=self.service.store.get('campaigns',cid)
        self.assertEqual(current['h0CandidateId'],row['id'])
        self.assertEqual(row['compositionId'],current['config']['h0CompositionId'])
        self.assertEqual(self.service.status(cid)['tables']['versions'][0]['label'],'H0')
        self.assertEqual(self.client.get('/campaigns/'+cid+'/h0').json()['validation'],'本活动尚未验证')
        with patch.object(self.service,'_verify_task_images'):
            self.service.control(cid,'start','start')
        self.assertFalse(self.service.store.list('trials',cid))
        self.service.store.update_plan(cid,{'parallelism':1,'closeoutReserveSeconds':0},'fixture plan','plan',0)
        self.service.store.submit(cid,row['id'],self.cfg['tasks'][:1],1,'one')
        self.assertEqual(len(self.service.store.list('trials',cid)),1)

    def test_replay_after_delete_keeps_selection_and_new_create_rejects_it(self):
        first=self.create(self.selection);lib=self.service.plugin_library;id=self.selection['plugins'][0]['id']
        lib.change(id,'delete',lib.preview(id)['versions'],'delete')
        replay=self.create(self.selection)
        self.assertEqual(first['id'],replay['id']);self.assertEqual(first['config'],replay['config'])
        lib.prune(lib.store.clock()+100)
        self.assertTrue((lib.root/id).exists())
        with self.assertRaises(Refused):self.create(self.selection,key='other')
        row=self.service.build_candidate(first['id'],[],'H0')
        self.assertEqual(row['libraryCapture']['plugins'][0]['id'],id)
        self.assertTrue(lib.get(id)['deleted'])
        empty=self.create({**self.selection,'plugins':[]},key='empty')
        self.assertFalse(self.service.build_candidate(empty['id'],[],'H0')['plugins'])
        with self.assertRaises(Conflict):self.create({**self.selection,'plugins':[]})

    def test_changed_workspace_cannot_replace_initial_selection(self):
        c=self.create(self.selection);root=self.service.workspace(c['id'])/'h0'
        materialize(self.service,self.selection,root);(root/'run.mjs').write_text('changed')
        with self.assertRaisesRegex(Refused,'偏离'):self.service.build_candidate(c['id'],[],'H0')
        self.assertFalse(self.service.store.list('candidates',c['id']))

    def test_unselected_catalog_and_origin_metadata_never_enter_activity_materials(self):
        from src.execution.bundle.project import SourceFiles
        files=SourceFiles();files['secret.mjs']=b'UNSELECTED_LIBRARY_SENTINEL'
        secret=self.service.plugin_library.save(files,{'name':'private-historical','version':'1'}, {'campaignId':'PRIVATE_ORIGIN_SENTINEL'})
        c=self.create(self.selection);cid=c['id'];candidate=self.service.build_candidate(cid,[],'H0')
        materials=self.service.materials
        self.assertEqual(materials.search(cid,'UNSELECTED_LIBRARY_SENTINEL',kind='plugin')['total'],0)
        self.assertEqual(materials.search(cid,'PRIVATE_ORIGIN_SENTINEL',kind='version')['total'],0)
        records=list(materials._records(cid,'plugin'));self.assertTrue(records)
        for row in records:self.service.meta_api.files.material(cid,row)
        directory=self.service.meta_api.files.directory(cid)
        self.assertFalse(any(b'UNSELECTED_LIBRARY_SENTINEL' in p.read_bytes() for p in directory.rglob('*') if p.is_file()))
        with self.assertRaises(Refused):materials.read(cid,'plugin:'+secret+':secret.mjs')
        self.assertNotIn('PRIVATE_ORIGIN_SENTINEL',json.dumps(candidate))

    def test_catalog_survives_actual_source_activity_deletion(self):
        c=self.create(self.selection);cid=c['id'];candidate=self.service.build_candidate(cid,[],'H0')
        id=self.selection['plugins'][0]['id'];lib=self.service.plugin_library
        preview=self.service.deletions.preview(cid)
        self.service.deletions.request(cid,preview['expectedRevision'],'delete-source')
        self.service.deletions.advance(cid)
        self.assertEqual(self.service.store.deletion(cid)['state'],'deleted')
        self.assertTrue(lib.contents(id)[0]);self.assertFalse(Path(candidate['bundlePath']).exists())
        self.assertTrue(resolve_selection(self.service,self.selection)['plugins'])
        self.assertTrue(any(not s['available'] for s in lib.origins(lib.get(id)) if s.get('campaignId')==cid))

    def test_selected_derivation_returns_to_library_without_exposing_other_origins(self):
        from src.execution.bundle.project import SourceFiles
        lib=self.service.plugin_library;materials=self.service.materials
        files=SourceFiles();files['index.mjs']=b'export function apply() {} // SELECTED_H05_SOURCE'
        manifest={'name':'h05-selected','version':'1','entry':'index.mjs',
                  'assembly':{'contract':'dsh-plugin-v1','entry':'index.mjs','requires':[]}}
        selected=lib.save(files,manifest,{'campaignId':'PRIVATE_SELECTED_ORIGIN'})
        files['index.mjs']=b'export function apply() {} // UNSELECTED_H05_SOURCE'
        secret=lib.save(files,{**manifest,'name':'h05-private'},{'campaignId':'PRIVATE_UNSELECTED_ORIGIN'})
        selection={**self.selection,'plugins':[{'id':selected,'config':{}}]}
        cid=self.create(selection)['id'];h0=self.service.build_candidate(cid,[],'H0')
        project=self.service.workspace(cid)/'derived'
        shutil.copytree(self.service.workspace(cid)/'h0',project)
        spec=json.loads((project/'harness.json').read_text())
        source=project/spec['plugins'][0]['path']/'index.mjs'
        source.write_text('export function apply() {} // DERIVED_H05_SOURCE')
        derived=self.service.build_candidate(cid,[],'Derived selected plugin',parent=h0['id'],project_path='derived')
        new_id=derived['libraryCapture']['plugins'][0]['id']
        self.assertNotEqual(selected,new_id)
        detail=self.client.get('/plugin-library/'+new_id,params={'file':'index.mjs'})
        self.assertEqual(detail.status_code,200);self.assertIn('DERIVED_H05_SOURCE',detail.json()['content'])
        self.assertTrue(any(s.get('campaignId')==cid for s in lib.get(new_id)['sources']))
        self.assertIn('SELECTED_H05_SOURCE',lib.detail(selected,'index.mjs')['content'])
        self.assertEqual(self.service.store.get('campaigns',cid)['h0CandidateId'],h0['id'])
        for candidate,marker in [(h0,'SELECTED_H05_SOURCE'),(derived,'DERIVED_H05_SOURCE')]:
            matches=materials.search(cid,marker,kind='plugin',candidateId=candidate['id'])['matches']
            self.assertEqual(len(matches),1)
            self.assertIn(marker,materials.read(cid,matches[0]['ref'])['text'])
        for marker in ['UNSELECTED_H05_SOURCE','PRIVATE_SELECTED_ORIGIN','PRIVATE_UNSELECTED_ORIGIN']:
            for kind in ['activity','version','plugin']:
                self.assertEqual(materials.search(cid,marker,kind=kind)['total'],0,(kind,marker))
            self.assertNotIn(marker,json.dumps(derived))
        for row in materials._records(cid,'plugin'):self.service.meta_api.files.material(cid,row)
        published=b''.join(p.read_bytes() for p in self.service.meta_api.files.directory(cid).rglob('*') if p.is_file())
        self.assertIn(b'DERIVED_H05_SOURCE',published);self.assertNotIn(b'UNSELECTED_H05_SOURCE',published)
        for ref in ['plugin:'+secret+':index.mjs','plugin:'+derived['id']+':candidate/../../control.sqlite']:
            with self.assertRaises(Refused):materials.read(cid,ref)

    def test_user_api_validation_and_meta_denial_before_lookup(self):
        c=self.create({**self.selection,'plugins':[]});cid=c['id']
        invalid=json.loads(json.dumps(self.selection));invalid['plugins'][0]['config']={}
        r=self.client.post('/plugin-library/h0/preview',json={'selection':invalid})
        self.assertEqual(r.status_code,403);self.assertIn('配置',r.text)
        for role in ('meta','meta-research'):
            _,token=self.service.lease(cid,role,self.service.store.clock()+100)
            headers={'Authorization':'Bearer '+token}
            selected=self.selection['plugins'][0]['id']
            for route in ['/plugin-library','/plugin-library?query=request&offset=1&includeDeleted=true',
                          '/plugin-library/h0/defaults','/campaigns/'+cid+'/h0','/plugin-library/jobs/unknown',
                          '/plugin-library/'+selected,'/plugin-library/'+selected+'?file=plugin.json',
                          '/plugin-library/'+selected+'/deletion','/plugin-library/'+'f'*64]:
                self.assertEqual(self.client.get(route,headers=headers).status_code,403,route)
            for route in ['/plugin-library/h0/preview','/plugin-library/rescan','/plugin-library/'+selected+'/change']:
                self.assertEqual(self.client.post(route,json={},headers=headers).status_code,403,route)
            existing=self.client.get('/plugin-library/'+selected,headers=headers)
            missing=self.client.get('/plugin-library/'+'f'*64,headers=headers)
            self.assertEqual(existing.json(),missing.json())

if __name__=='__main__':unittest.main()
