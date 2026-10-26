import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.control.service import ControlService
from src.control.meta_composition import freeze as freeze_meta
from src.control.meta_contracts import CONTRACTS
from src.control.meta_api import validate
from src.execution.bundle.project import source_tar
from src.execution.bundle.manifest import digest, resolve

ROOT=Path(__file__).resolve().parents[2]


class ProcessCandidatesTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.service=ControlService(ROOT,self.root/'data',ROOT.parent/'Quantum-Harbor','http://127.0.0.1:1')
        self.addCleanup(self.service.pool.shutdown)
        model={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
        cfg={'solver':model,'meta':model,'tasks':['time_budgeted_hamlearn_10q'],'concurrency':1,'wallTimeSeconds':20000,
             'executionContract':'harbor-process-v1','executionResources':json.loads((ROOT/'schemas/execution/process-resources.json').read_text())}
        self.cid=self.service.store.create(cfg,'fixture')['id']
        def built(contents,spec,cache,log,resources,**kwargs):
            artifact=self.root/(digest(source_tar(contents))+'.tar');artifact.write_bytes(source_tar(contents))
            return artifact,{'artifactSha256':digest(artifact.read_bytes()),'status':'passed','inputs':{'sources':{n:digest(v) for n,v in contents.items()}}}
        mock=patch('src.execution.bundle.project.build',side_effect=built);mock.start();self.addCleanup(mock.stop)

    def test_same_operations_accept_complete_project_and_preserve_solver(self):
        baseline=self.service.build_candidate(self.cid,[],'H0')
        project=self.service.workspace(self.cid)/'h0';spec=json.loads((project/'harness.json').read_text())
        spec['runtimeConfig']['sessions']=3;spec['runtimeConfig']['plugins']=[];spec['framework']={'package':'another-framework','version':'2'}
        (project/'harness.json').write_text(json.dumps(spec))
        checked=self.service.build_candidate(self.cid,[],'check',check_only=True,project_path='/work/plugins/h0')
        candidate=self.service.build_candidate(self.cid,[],'Changed complete Harness',parent=baseline['id'],project_path='/work/plugins/h0')
        self.assertNotEqual(baseline['bundleId'],candidate['bundleId'])
        self.assertEqual(checked['bundleId'],candidate['bundleId'])
        self.assertEqual(candidate['project']['runtimeConfig']['sessions'],3)
        a=json.loads(resolve(baseline['bundlePath']).asset('recipe.json').read_text())
        b=json.loads(resolve(candidate['bundlePath']).asset('recipe.json').read_text())
        self.assertEqual(a,b);self.assertNotIn('maxTokens',b)
        self.assertEqual(self.service.knowledge_for(self.cid).manifest['dshVersion'],'0.2.1-rc.2')

    def test_project_tool_schema_and_legacy_protocol_are_separate(self):
        for op in ['candidate_check','candidate_freeze']:
            args={'projectPath':'h0','idempotencyKey':'one',**({'description':'Change'} if op.endswith('freeze') else {})}
            validate(args,CONTRACTS['meta-tools-v9'][op]['input'])
            with self.assertRaises(ValueError):validate(args,CONTRACTS['meta-tools-v8'][op]['input'])

    def test_project_cannot_escape_workspace(self):
        with self.assertRaises(ValueError):self.service.build_candidate(self.cid,[],'bad',project_path='../outside')

    def test_library_keeps_failed_source_and_frozen_origin_is_not_required(self):
        self.service.build_candidate(self.cid,[],'H0')
        project=self.service.workspace(self.cid)/'h0'
        plugin=project/'plugins/example';plugin.mkdir(parents=True)
        (plugin/'index.mjs').write_text('export function apply() {}')
        (plugin/'plugin.json').write_text(json.dumps({'name':'example','version':'1','entry':'index.mjs'}))
        spec=json.loads((project/'harness.json').read_text());spec['plugins']=[{'name':'example','path':'plugins/example'}]
        (project/'harness.json').write_text(json.dumps(spec))
        with patch('src.execution.bundle.project.build',side_effect=RuntimeError('fixture build failed')):
            with self.assertRaisesRegex(RuntimeError,'fixture build failed'):
                self.service.build_candidate(self.cid,[],'failed',project_path='h0')
        item=self.service.plugin_library.page()['items'][0]
        self.assertEqual(item['buildStatus'],'failed')
        candidate=self.service.build_candidate(self.cid,[],'passed',project_path='h0')
        imported=self.service.plugin_library.import_candidate(candidate)
        self.assertEqual(imported['plugins'][0]['id'],item['id'])
        import shutil
        shutil.rmtree(project);shutil.rmtree(candidate['bundlePath'])
        self.assertIn('apply',self.service.plugin_library.detail(item['id'],'index.mjs')['content'])

    def test_library_http_requires_user_before_any_lookup(self):
        from fastapi.testclient import TestClient
        from src.control.server import make_app
        _,token=self.service.lease(self.cid,'meta',self.service.store.clock()+100)
        client=TestClient(make_app(self.service,supervise=False))
        for path in ['/plugin-library','/plugin-library/'+'a'*64,'/plugin-library/jobs/unknown']:
            self.assertEqual(client.get(path,headers={'authorization':'Bearer '+token}).status_code,403)
        self.assertEqual(client.get('/plugin-library',headers={'authorization':'Bearer '+self.service.user_token}).status_code,200)
