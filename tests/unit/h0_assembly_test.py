import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from src.control.store import Store, Refused
from src.control.plugin_library import PluginLibrary
from src.control.h0 import defaults, resolve_selection, materialize
from src.execution.bundle.project import SourceFiles

ROOT=Path(__file__).resolve().parents[2]

class H0AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.data=Path(self.tmp.name)
        self.service=SimpleNamespace(source=ROOT,data=self.data,store=Store(self.data/'control.sqlite'))
        self.lib=PluginLibrary(self.service);self.service.plugin_library=self.lib
        self.defaults=defaults(self.service)
        self.selection={k:self.defaults[k] for k in ('version','templateId','plugins')}

    def test_exact_configuration_identity_and_no_unselected_sources(self):
        complete=resolve_selection(self.service,self.selection)
        empty=resolve_selection(self.service,{**self.selection,'plugins':[]})
        self.assertTrue(complete['project']['plugins']);self.assertFalse(empty['project']['plugins'])
        self.assertFalse(any('recovery' in n for n in empty['files']))
        self.assertNotIn('recovery',empty['project']['runtimeConfig'])
        self.assertNotIn(b'config.recovery',empty['files']['run.mjs'])
        self.assertNotEqual(complete['compositionId'],empty['compositionId'])
        self.assertEqual(complete['compositionId'],resolve_selection(self.service,self.selection)['compositionId'])
        self.selection['plugins'][0]['config']['policy']['maxChainRetries']=3
        changed=resolve_selection(self.service,self.selection)
        self.assertNotEqual(changed['compositionId'],complete['compositionId'])
        self.assertEqual(changed['plugins'][0]['id'],complete['plugins'][0]['id'])

    def test_deleted_default_is_not_recreated_and_frozen_selection_still_works(self):
        id=self.selection['plugins'][0]['id']
        self.lib.change(id,'delete',self.lib.preview(id)['versions'],'delete')
        self.assertEqual(defaults(self.service)['missing'],[id])
        with self.assertRaises(Refused):resolve_selection(self.service,self.selection)
        self.assertEqual(resolve_selection(self.service,self.selection,frozen=True)['plugins'][0]['id'],id)
        self.assertTrue(self.lib.get(id)['deleted'])
        self.lib.prune(self.service.store.clock()+1)
        defaults(self.service)
        self.assertFalse((self.lib.root/id).exists())
        self.assertFalse(resolve_selection(self.service,{**self.selection,'plugins':[]})['plugins'])
        self.lib.change(id,'restore',self.lib.preview(id)['versions'],'explicit-restore')
        self.assertFalse(self.lib.get(id)['deleted'])
        self.assertTrue(resolve_selection(self.service,self.selection)['plugins'])

    def test_requires_config_conflicts_and_path_safety(self):
        files=SourceFiles();files['index.mjs']=b'export function apply(){}'
        manifest={'name':'fixture','version':'1','assembly':{'contract':'dsh-plugin-v1','entry':'index.mjs','requires':[self.selection['plugins'][0]['id']],
                  'configSchema':{'type':'object','required':['value'],'properties':{'value':{'type':'integer'}}}}}
        id=self.lib.save(files,manifest,{'kind':'fixture'})
        chosen={'id':id,'config':{'value':3}}
        with self.assertRaisesRegex(Refused,'依赖'):resolve_selection(self.service,{**self.selection,'plugins':[chosen]})
        good=resolve_selection(self.service,{**self.selection,'plugins':[chosen,*self.selection['plugins']]})
        self.assertEqual(good['plugins'][-1]['id'],id)
        with self.assertRaisesRegex(Refused,'配置'):resolve_selection(self.service,{**self.selection,'plugins':[{'id':id,'config':{}},*self.selection['plugins']]})
        manifest['assembly']['conflicts']=['request-recovery'];conflict=self.lib.save(files,manifest,{'kind':'fixture'})
        with self.assertRaisesRegex(Refused,'冲突'):resolve_selection(self.service,{**self.selection,'plugins':[{'id':conflict,'config':{'value':3}},*self.selection['plugins']]})
        manifest['assembly']['entry']='../escape';bad=self.lib.save(files,manifest,{'kind':'fixture'})
        with self.assertRaises(Refused):resolve_selection(self.service,{**self.selection,'plugins':[{'id':bad,'config':{}}]})
        manifest['assembly'].update(entry='index.mjs',requires=[],conflicts=[],configSchema={'$ref':'https://invalid.example/schema'})
        external=self.lib.save(files,manifest,{'kind':'fixture'})
        self.assertEqual(self.lib.compatibility(self.lib.get(external))['state'],'needs_adaptation')
        manifest['assembly']['configSchema']={'$ref':'#/$defs/missing'}
        broken=self.lib.save(files,manifest,{'kind':'fixture'})
        with self.assertRaisesRegex(Refused,'内部引用'):resolve_selection(self.service,{**self.selection,'plugins':[{'id':broken,'config':{}}]})

    def test_native_loader_accepts_selected_and_empty_projects_and_rejects_missing_service(self):
        for i,selection in enumerate([self.selection,{**self.selection,'plugins':[]}]):
            out=self.data/str(i);materialize(self.service,selection,out)
            (out/'node_modules').symlink_to(ROOT/'node_modules',target_is_directory=True)
            result=subprocess.run(['node','check-assembly.mjs'],cwd=out,capture_output=True,text=True,timeout=70)
            self.assertEqual(result.returncode,0,result.stderr)
            receipt=json.loads((out/'assembly-check.json').read_text())
            self.assertEqual(len(receipt['plugins']),len(selection['plugins']))
        (out/'bad.mjs').write_text("export const name='bad';export const inject=['missingService'];export function apply(){}")
        spec=json.loads((out/'harness.json').read_text());spec['runtimeConfig']['plugins']=[{'id':'bad','name':'./bad.mjs'}]
        (out/'harness.json').write_text(json.dumps(spec))
        result=subprocess.run(['node','check-assembly.mjs'],cwd=out,capture_output=True,text=True,timeout=70)
        self.assertNotEqual(result.returncode,0);self.assertIn('missingService',result.stderr)

    def test_materialized_project_uses_only_pinned_contents(self):
        out=self.data/'project';resolved=materialize(self.service,self.selection,out)
        self.assertEqual(json.loads((out/'harness.json').read_text()),resolved['project'])
        self.assertTrue((out/'plugins'/self.selection['plugins'][0]['id']/'plugin.json').is_file())
        with self.assertRaises(Refused):materialize(self.service,self.selection,out)
        capture=self.lib.capture(resolved['files'],resolved['project'],{'campaignId':'target'})
        self.assertEqual(capture['plugins'][0]['id'],self.selection['plugins'][0]['id'])

if __name__=='__main__':unittest.main()
