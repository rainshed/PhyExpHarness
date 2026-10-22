import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('ui_boundaries',ROOT/'scripts/check-boundaries.py')
boundary=importlib.util.module_from_spec(spec);spec.loader.exec_module(boundary)

class UIBoundaries(unittest.TestCase):
 def test_ui_package_source_css_and_transitive_edges(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   def write(name,text):
    file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(text)
   for name,kind in [('alpha','ui'),('beta','ui'),('client','client')]:
    write(f'packages/{name}/package.json',json.dumps({'name':'@phyexp/'+name,'phyexpWorkbench':{'kind':kind},'exports':{'.':'./index.ts'}}))
    write(f'packages/{name}/index.ts','export const value=1;')
   write('packages/alpha/index.ts',"import {value} from '@phyexp/client';")
   self.assertEqual(boundary.violations(root),[])
   for code in ["import '@phyexp/beta';", "import '../beta/index';", "import './nested';"]:
    write('packages/alpha/index.ts',code)
    write('packages/alpha/nested.tsx',"import './layout.css';")
    write('packages/alpha/layout.css',"@import '../beta/theme.css';")
    self.assertTrue(any('concrete UI' in e for e in boundary.violations(root)))
   write('packages/alpha/index.ts',"import '@phyexp/client';")
   write('packages/alpha/nested.tsx','export const x=1;');write('packages/alpha/layout.css','')
   write('packages/client/index.ts',"export {value} from '@phyexp/beta';")
   self.assertTrue(any('concrete UI' in e for e in boundary.violations(root)))
   write('packages/client/index.ts',"export const value=document.title;")
   self.assertTrue(any('presentation' in e for e in boundary.violations(root)))
   write('packages/client/index.ts','export const value=1;')
   write('packages/alpha/index.ts',"import '../client/index';")
   self.assertTrue(any('public package exports' in e for e in boundary.violations(root)))
   write('packages/alpha/index.ts',"import '@phyexp/client/internal';")
   self.assertTrue(any('public package exports' in e for e in boundary.violations(root)))
   write('packages/alpha/index.ts','export const value=1;')
   write('packages/alpha/package.json',json.dumps({'name':'@phyexp/alpha','phyexpWorkbench':{'kind':'ui'},'dependencies':{'@phyexp/beta':'*'}}))
   self.assertTrue(any('concrete UI' in e for e in boundary.violations(root)))
