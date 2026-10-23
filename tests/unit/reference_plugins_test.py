import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.control.store import Refused
from src.control.reference.plugins import configure, contracts, entry_path
from src.control.meta_native_composition import freeze, verify, validate
ROOT=Path(__file__).resolve().parents[2]

class ReferencePluginsTest(unittest.TestCase):
    def test_unselected_package_can_be_absent(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)
            shutil.copytree(ROOT/'packages/meta-harness',source/'packages/meta-harness')
            base=json.loads((source/'packages/meta-harness/composition-native.json').read_text())
            validate(configure(source,base,{'modelEnabled':False,'harnessEnabled':False}),source)
            for axis in ['model','harness']:
                with self.assertRaises(Refused):configure(source,base,{axis+'Enabled':True})
                shutil.copytree(ROOT/'packages'/('meta-'+axis+'-reference'),source/'packages'/('meta-'+axis+'-reference'))
                composition=configure(source,base,{axis+'Enabled':True})
                validate(composition,source)
                self.assertEqual(list(contracts(source,composition,{})),['meta-'+axis+'-reference'])
                shutil.rmtree(source/'packages'/('meta-'+axis+'-reference'))
    def test_frozen_optional_assets_survive_package_removal_and_cache_rebuild(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp)/'data';data.mkdir()
            with patch('src.control.meta_native_composition.prepare_image',return_value='sha256:'+'a'*64):
                reference=freeze(ROOT,data,{'solver':{'model':'fixture'},'referencePolicy':{'modelEnabled':True,'harnessEnabled':True}})
            self.assertEqual(len(reference['optionalToolContracts']),2)
            runtime,manifest=verify(data,reference,ROOT)
            for axis in ['model','harness']:
                self.assertIn(f'packages/meta-{axis}-reference/contracts.json',manifest['files'])
            shutil.rmtree(runtime)
            # The new checkout has no optional source packages, only the same dependencies.
            checkout=Path(temp)/'checkout';checkout.mkdir()
            shutil.copyfile(ROOT/'package-lock.json',checkout/'package-lock.json')
            runtime,_=verify(data,reference,checkout)
            self.assertTrue((runtime/'packages/meta-model-reference/index.mjs').is_file())
            self.assertTrue((runtime/'packages/meta-harness-reference/index.mjs').is_file())
    def test_workspace_links_do_not_invalidate_runtime_but_dependency_changes_do(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp)/'data';data.mkdir();source=Path(temp)/'source';source.mkdir()
            with patch('src.control.meta_native_composition.prepare_image',return_value='sha256:'+'a'*64):
                reference=freeze(ROOT,data,{'solver':{'model':'fixture'}})
            lock=json.loads((ROOT/'package-lock.json').read_text())
            lock['packages']['node_modules/@phyexp/extra']={'link':True,'resolved':'packages/extra'}
            (source/'package-lock.json').write_text(json.dumps(lock))
            shutil.rmtree(data/'cache/meta-runtimes'/reference['id'])
            runtime,_=verify(data,reference,source)
            self.assertTrue(runtime.is_dir())
            lock['packages']['node_modules/ajv']['version']='changed'
            (source/'package-lock.json').write_text(json.dumps(lock))
            with self.assertRaises(Refused):verify(data,reference,source)
    def test_contract_collisions_and_package_spoofing_refused(self):
        with self.assertRaises(Refused):entry_path({'id':'meta-model-reference','module':'domain-control.mjs'})
        base=json.loads((ROOT/'packages/meta-harness/composition-native.json').read_text())
        composition=configure(ROOT,base,{'modelEnabled':True})
        with self.assertRaises(Refused):contracts(ROOT,composition,{'reference_model_submit':{}})

if __name__=='__main__':unittest.main()
