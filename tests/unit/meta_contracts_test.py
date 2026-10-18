import unittest,tempfile,importlib.util,json
from pathlib import Path
from jsonschema import Draft202012Validator,ValidationError
from src.control.knowledge import KnowledgePack
ROOT=Path(__file__).resolve().parents[2]
def load(name,file):
 spec=importlib.util.spec_from_file_location(name,ROOT/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
boundary=load('boundaries','scripts/check-boundaries.py')
class Contracts(unittest.TestCase):
 def test_dependency_graph_rejects_indirect_platform_and_plugin_imports(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)
   for name,text in {'src/execution/run.mjs':"import '../shared.mjs';",'src/shared.mjs':"import './control/db.mjs';",'src/control/db.mjs':'export const db=1;', 'packages/meta-harness/index.mjs':"import '../../src/control/db.mjs';"}.items():
    f=p/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(text)
   self.assertEqual(len(boundary.violations(p)),2)
   (p/'src/shared.mjs').write_text('export const value=1;');(p/'packages/meta-harness/index.mjs').write_text('export const value=1;')
   self.assertEqual(boundary.violations(p),[])
 def test_sdk_version_integrity_ranges_and_public_surface(self):
  p=KnowledgePack(ROOT/'knowledge/plugin-sdk/reference','0.2.1-rc.2')
  self.assertTrue(p.search('post-execute')['matches'])
  self.assertEqual(p.inspect('ctx.credentials.resolve')['availability'],'unavailable')
  self.assertEqual(p.inspect('ctx.tools.register')['availability'],'declared-in-execution-sdk')
  for name in ['../../AGENTS.md','secret']:self.assertRaises(ValueError,p.read,name)
  self.assertRaises(ValueError,KnowledgePack,p.path,'wrong')
  self.assertRaises(ValueError,KnowledgePack,p.path,'0.2.1-rc.2','wrong-profile')
  self.assertRaises(ValueError,p.read,'tools',-1)
 def test_schemas_keep_unscored_and_unknown_distinct_from_zero(self):
  defs=json.loads((ROOT/'schemas/contracts.schema.json').read_text())['$defs']
  for name,schema in defs.items():Draft202012Validator.check_schema(schema)
  v=Draft202012Validator(defs['Trial'])
  for score in [0,None]:v.validate({'id':'t','batchId':'b','launchId':'l','state':'failed','score':score,'usage':{}})
  self.assertRaises(ValidationError,v.validate,{'id':'t'})
  v=Draft202012Validator(defs['Usage']);v.validate({'id':'r','purpose':'solver','status':'unknown','confirmedTokens':None,'reservedTokens':100})
  self.assertRaises(ValidationError,v.validate,{'id':'r','purpose':'solver','status':'known','confirmedTokens':-1,'reservedTokens':0})
