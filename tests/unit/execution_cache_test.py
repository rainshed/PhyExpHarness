import io
import json
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from src.execution.bundle.freeze import freeze
from src.execution.bundle.manifest import resolve, verify
from src.control.execution_cache import prepare_runtime

ROOT=Path(__file__).resolve().parents[2]


class ExecutionCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='phyexp cache ')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.recipe=json.loads((ROOT/'recipes/h0-sol.json').read_text())
        self.a=freeze(ROOT,self.base/'store',self.recipe)
        self.b=freeze(ROOT,self.base/'store',{**self.recipe,'maxOutputChars':12345})
        self.installs=0;self.counter=threading.Lock()
        self.platform=json.dumps({'platform':'fixture','arch':'arm64','abi':'137','node':'24'})
        self.addCleanup(patch.stopall)
        patch('src.control.execution_cache.subprocess.check_output',side_effect=lambda *a,**k:self.platform).start()
        patch('src.control.execution_cache.subprocess.run',side_effect=self.install).start()

    def install(self,argv,**kwargs):
        self.assertEqual(argv,['npm','ci','--ignore-scripts','--no-audit','--no-fund'])
        with self.counter:self.installs+=1
        folder=Path(kwargs['cwd'])/'node_modules/fixture'
        folder.mkdir(parents=True)
        (folder/'index.js').write_text('locked dependency')
        bin=folder.parent/'.bin';bin.mkdir();(bin/'fixture').symlink_to('../fixture/index.js')

    def prepare(self,row=None):
        return prepare_runtime((row or self.a)['path'],self.base/'cache',io.StringIO())

    def test_concurrent_candidates_share_complete_read_only_installation(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths=list(pool.map(self.prepare,[self.a,self.b,self.a,self.b]))
        self.assertEqual(self.installs,1);self.assertEqual(len(set(paths)),1)
        modules=(paths[0]/'node_modules').resolve()
        self.assertEqual((modules/'fixture/index.js').stat().st_mode & 0o222,0)
        self.assertFalse((Path(self.a['path'])/'node_modules').exists())
        self.assertNotIn('recipe.json',{p.name for p in paths[0].iterdir()})
        self.assertEqual(verify(self.a['path'])['id'],self.a['id'])

    def test_dependency_damage_and_missing_cache_publish_new_generations(self):
        first=self.prepare();modules=(first/'node_modules').resolve()
        asset=modules/'fixture/index.js';asset.chmod(0o644);asset.write_text('corrupt')
        repaired=self.prepare()
        self.assertNotEqual(first,repaired);self.assertTrue(first.exists())
        self.assertEqual((repaired/'node_modules/fixture/index.js').read_text(),'locked dependency')
        self.assertEqual(self.installs,2)
        pointer=next((self.base/'cache/dependencies').glob('*.json'));pointer.unlink()
        third=self.prepare()
        self.assertNotEqual(third,repaired);self.assertEqual(self.installs,3)

    def test_adapter_damage_repairs_without_reinstalling_dependencies(self):
        first=self.prepare();entry=first/'run.py';entry.chmod(0o644);entry.write_text('corrupt')
        repaired=self.prepare()
        self.assertNotEqual(first,repaired);self.assertEqual(self.installs,1)
        self.assertEqual((repaired/'run.py').read_bytes(),resolve(self.a['path']).asset('run.py').read_bytes())

    def test_different_platform_or_abi_cannot_reuse_installation(self):
        first=self.prepare();self.platform=json.dumps({'platform':'fixture','arch':'x64','abi':'138','node':'24'})
        second=self.prepare()
        self.assertNotEqual(first,second);self.assertEqual(self.installs,2)

    def test_failed_install_never_publishes_or_falls_back(self):
        with patch('src.control.execution_cache.subprocess.run',side_effect=subprocess.CalledProcessError(1,['npm','ci'])):
            with self.assertRaises(subprocess.CalledProcessError):self.prepare()
        self.assertEqual(list((self.base/'cache/dependencies').glob('*.json')),[])
        self.assertEqual(verify(self.a['path'])['id'],self.a['id'])

    def test_migrated_legacy_view_repairs_shared_install_without_changing_identity(self):
        runtime=self.prepare()
        old=freeze(ROOT,self.base/'store',self.recipe,legacy=True)
        root=Path(old['path'])
        (root/'node_modules').symlink_to((runtime/'node_modules').resolve(),target_is_directory=True)
        previous=(root/'node_modules').resolve()
        asset=previous/'fixture/index.js';asset.chmod(0o644);asset.write_text('damaged cache')
        result=prepare_runtime(root,self.base/'cache',io.StringIO())
        self.assertEqual(result,root.resolve())
        self.assertNotEqual((root/'node_modules').resolve(),previous)
        self.assertEqual((root/'node_modules/fixture/index.js').read_text(),'locked dependency')
        self.assertEqual(verify(root)['id'],old['id'])
