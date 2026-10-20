import copy
import json
import tempfile
import unittest
from jsonschema import ValidationError
from pathlib import Path
from src.execution.bundle.freeze import freeze, verify
from src.exporting.project import export_project
ROOT=Path(__file__).resolve().parents[2]

class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='phyexp bundle ')
        self.base=Path(self.temp.name)
        self.recipe=json.loads((ROOT/'recipes/h0-sol.json').read_text())
        self.plugin=self.base/'draft';self.plugin.mkdir()
        self.manifest={'schemaVersion':1,'name':'technical-echo','version':'1.0.0','entry':'index.mjs',
            'purpose':'Technical test','configSchema':{'type':'object','properties':{'prefix':{'type':'string'}},'additionalProperties':False},
            'dependencies':[],'observes':['tool-results'],'intervenes':['tool-results'],
            'capabilities':['tools'],'fallbackBehavior':'Propagate errors','assets':[],'tools':['example_echo']}
        (self.plugin/'plugin.json').write_text(json.dumps(self.manifest))
        (self.plugin/'index.mjs').write_text((ROOT/'knowledge/plugin-sdk/examples/echo.mjs').read_text())
    def tearDown(self):self.temp.cleanup()
    def freeze(self, selections=()):return freeze(ROOT,self.base/'store',self.recipe,selections)
    def test_frozen_code_and_export_identity_survive_draft_edit_and_relocation(self):
        b=self.freeze([{'path':self.plugin,'config':{'prefix':'x:'}}]);p=Path(b['path'])
        (self.plugin/'index.mjs').write_text('throw new Error("changed draft");')
        self.assertEqual(verify(p)['id'],b['id'])
        e=export_project(p,self.base/'export with spaces');self.assertEqual(verify(e['path'])['id'],b['id'])
        self.assertFalse((Path(e['path'])/'packages').exists())
        self.assertNotEqual((p/'plugins/technical-echo/index.mjs').read_text(),(self.plugin/'index.mjs').read_text())
        asset=p/'recipe.json';asset.chmod(0o644);asset.write_text('{}')
        self.assertRaises(ValueError,verify,p)
    def test_deepseek_export_carries_catalog_and_native_adapter_dependency_without_credentials(self):
        self.recipe.update(provider='deepseek-official',model='deepseek-flash',reasoningEffort='high')
        bundle=self.freeze()
        exported=export_project(bundle['path'],self.base/'deepseek export')
        project=Path(exported['path'])
        self.assertEqual(verify(project)['id'],bundle['id'])
        self.assertEqual(json.loads((project/'recipe.json').read_text())['provider'],'deepseek-official')
        self.assertIn('@deepseek-ai/dsh-llm-deepseek-api-key',json.loads((project/'package.json').read_text())['dependencies'])
        catalog=json.loads((project/'src/execution/host/model-catalog.json').read_text())
        self.assertEqual(catalog['providers']['deepseek-official']['models'][0]['versionPolicy'],'rolling-alias')
        self.assertFalse(list(project.rglob('credentials.json')))

    def test_invalid_dependencies_capabilities_configuration_and_assets_rejected(self):
        for key,value in [('dependencies',['missing']),('capabilities',['credentials']),('entry','../escape.mjs'),('tools',['bash'])]:
            m={**self.manifest,key:value};(self.plugin/'plugin.json').write_text(json.dumps(m))
            expected = ValidationError if key == 'capabilities' else ValueError
            self.assertRaises(expected,self.freeze,[{'path':self.plugin,'config':{}}])
        (self.plugin/'plugin.json').write_text(json.dumps(self.manifest))
        self.assertRaises(ValidationError,self.freeze,[{'path':self.plugin,'config':{'unknown':True}}])
        (self.plugin/'index.mjs').unlink();(self.plugin/'index.mjs').symlink_to(ROOT/'package.json')
        self.assertRaises(ValueError,self.freeze,[{'path':self.plugin}])
    def test_ablation_and_dependency_order_are_content_addressed(self):
        first=self.freeze([{'path':self.plugin}]);empty=self.freeze();again=self.freeze()
        self.assertNotEqual(first['id'],empty['id']);self.assertEqual(empty['id'],again['id'])
        self.assertEqual(empty['plugins'],[])

    def test_finder_metadata_is_ignored_but_unlisted_execution_file_is_rejected(self):
        b=self.freeze();root=Path(b['path']);(root/'.DS_Store').write_bytes(b'finder metadata')
        self.assertEqual(verify(root)['id'],b['id'])
        (root/'unexpected.mjs').write_text('export const value=1;')
        with self.assertRaises(ValueError):verify(root)
