import copy
import json
import tempfile
import unittest
import shutil
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from jsonschema import ValidationError
from pathlib import Path
from src.execution.bundle.freeze import freeze, verify
from src.exporting.project import export_project
from src.execution.bundle.manifest import resolve, canonical, digest, read_plugins
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
        self.assertNotEqual(resolve(p).asset('plugins/technical-echo/index.mjs').read_text(),(self.plugin/'index.mjs').read_text())
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

    def test_freeze_rejects_workspace_changes_before_publication(self):
        read=Path.read_bytes;changed=False
        def racing(file):
            nonlocal changed
            value=read(file)
            if file.resolve()==(self.plugin/'index.mjs').resolve() and not changed:
                changed=True;file.write_bytes(value+b'\n// concurrent writer\n')
            return value
        with patch.object(Path,'read_bytes',racing):
            with self.assertRaisesRegex(ValueError,'changed during freeze'):self.freeze([{'path':self.plugin}])
        self.assertFalse(list((self.base/'store').glob('*/bundle.json')))

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

    def test_config_changes_share_objects_and_only_two_candidate_files(self):
        a=self.freeze([{'path':self.plugin,'config':{'prefix':'a:'}}])
        b=self.freeze([{'path':self.plugin,'config':{'prefix':'b:'}}])
        self.assertNotEqual(a['id'],b['id'])
        self.assertEqual(resolve(a['path']).objects,resolve(b['path']).objects)
        for row in (a,b):
            self.assertEqual({f.name for f in Path(row['path']).iterdir()},{'bundle.json','recipe.json'})
            self.assertNotIn('node_modules',str(resolve(row['path']).assets))
        self.assertEqual(len(list((self.base/'store').iterdir())),5) # three objects, two compositions
        files=read_plugins(a['path'],'technical-echo')['files']
        self.assertIn('technical-echo/index.mjs',files)
        self.assertIn('content',read_plugins(a['path'],'technical-echo/index.mjs'))

    def test_same_name_and_version_new_content_never_overwrites_old_plugin(self):
        first=self.freeze([{'path':self.plugin}])
        source=resolve(first['path']).asset('plugins/technical-echo/index.mjs').read_bytes()
        (self.plugin/'index.mjs').write_text('export default ()=>{};')
        second=self.freeze([{'path':self.plugin}])
        self.assertNotEqual(first['plugins'][0]['object'],second['plugins'][0]['object'])
        self.assertEqual(resolve(first['path']).asset('plugins/technical-echo/index.mjs').read_bytes(),source)

    def test_concurrent_publish_and_document_identity_are_stable(self):
        def build(i):
            return freeze(ROOT,self.base/'store',self.recipe,[{'path':self.plugin}],
                          {'id':'documentation-'+str(i),'profileDigest':'fixed-profile'})
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows=list(pool.map(build,range(8)))
        self.assertEqual(len({b['id'] for b in rows}),1)
        self.assertEqual(len(list((self.base/'store').iterdir())),4)
        verify(rows[0]['path'])

    def test_recipe_labels_notes_and_timestamps_do_not_change_execution_identity(self):
        first=self.freeze()
        self.recipe.update(id='renamed',name='Display name',notes='Different documentation',createdAt=123)
        self.assertEqual(first['id'],self.freeze()['id'])

    def test_portable_export_survives_store_removal_and_rejects_missing_or_tampered_objects(self):
        b=self.freeze([{'path':self.plugin}])
        exported=Path(export_project(b['path'],self.base/'exports')['path'])
        shutil.rmtree(self.base/'store')
        self.assertEqual(verify(exported)['id'],b['id'])
        self.assertFalse((exported/'src/execution/bundle/freeze.py').exists())
        catalog=exported/'objects.json'
        original=catalog.read_bytes();catalog.write_text('{}')
        with self.assertRaisesRegex(ValueError,'identity mismatch'):verify(exported)
        catalog.write_bytes(original)
        asset=exported/'plugins/technical-echo/index.mjs';asset.unlink()
        with self.assertRaisesRegex(ValueError,'Missing'):verify(exported)

    def test_object_symlinks_and_content_damage_fail_without_fallback(self):
        b=self.freeze([{'path':self.plugin}]);resolved=resolve(b['path'])
        root=resolved.plugin_roots['technical-echo'];saved=root.with_name('saved-assets');root.rename(saved)
        root.symlink_to(saved,target_is_directory=True)
        with self.assertRaises(ValueError):verify(b['path'])
        root.unlink();saved.rename(root)
        source=root/'index.mjs';source.chmod(0o644);source.write_text('modified')
        with self.assertRaisesRegex(ValueError,'asset mismatch'):verify(b['path'])

    def test_false_framework_reference_cannot_be_reidentified_as_valid(self):
        b=self.freeze();path=Path(b['path'])/'bundle.json'
        raw=json.loads(path.read_text());raw['framework']['version']='latest'
        raw['id']=digest(canonical({k:v for k,v in raw.items() if k!='id'}))
        path.chmod(0o644);path.write_bytes(canonical(raw)+b'\n')
        with self.assertRaisesRegex(ValueError,'Framework reference'):verify(path.parent)

    def test_legacy_bundle_read_and_export_keep_original_identity(self):
        b=freeze(ROOT,self.base/'legacy',self.recipe,[{'path':self.plugin}],legacy=True)
        before={str(p):p.read_bytes() for p in Path(b['path']).rglob('*') if p.is_file()}
        exported=export_project(b['path'],self.base/'exports')
        self.assertEqual(verify(exported['path'])['id'],b['id'])
        self.assertEqual(verify(exported['path'])['schemaVersion'],1)
        self.assertEqual(before,{str(p):p.read_bytes() for p in Path(b['path']).rglob('*') if p.is_file()})
