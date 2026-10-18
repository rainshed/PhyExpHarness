import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from src.control.store import Store,Refused
from src.reporting.tables import build_tables,readable_text,markdown_tables
from src.reporting.reports import Reports
from src.control.inspection import plugin_source,open_folder
from src.execution.bundle.freeze import freeze

ROOT=Path(__file__).resolve().parents[2]
MODEL={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
def config():return {'name':'Test','solver':MODEL,'meta':MODEL,'tasks':['adaptive_clustered_clbcs_h2o'],'wallTimeSeconds':12600,'concurrency':3,'maxRounds':None,'maxTrials':None,'softTokenLimit':None,'trialTimeSeconds':None,'reserveSeconds':None,'reserveTokens':None}

class OptionalLimitsTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.now=1000
  self.store=Store(Path(self.temp.name)/'db',clock=lambda:self.now);self.c=self.store.create(config(),'c')['id'];self.store.control(self.c,'start','start')
  self.candidate=self.store.candidate(self.c,{'id':'test','path':'/none','plugins':[]},'base',check={'status':'passed'})['id']
 def test_unlimited_rounds_trials_still_count_and_concurrency_three(self):
  for i in range(20):self.store.submit(self.c,self.candidate,config()['tasks'],1,str(i))
  with ThreadPoolExecutor(8) as pool:claims=list(pool.map(lambda _:self.store.claim(self.c),range(8)))
  self.assertEqual(sum(t is not None for t in claims),3)
  self.assertEqual(self.store.status(self.c)['counts']['rounds'],20)
  self.assertFalse(self.store.status(self.c)['explorationClosed'])
 def test_unlimited_tokens_keep_unknown_and_confirmed_accounting(self):
  self.store.reserve(self.c,'lease','huge',90_000_000,'meta');self.store.settle(self.c,'lease','huge',None,True)
  self.store.reserve(self.c,'lease','next',300000,'solver');self.store.settle(self.c,'lease','next',400000,False)
  self.assertEqual(self.store.usage(self.c)['unknownReservedTokens'],90_000_000)
  self.assertEqual(self.store.usage(self.c)['confirmedTokens'],400000)
 def test_finite_time_closeout_pause_and_restart_remain_enforced(self):
  self.store.submit(self.c,self.candidate,config()['tasks'],1,'b');self.now=12690
  t=self.store.claim(self.c);self.assertEqual(t['deadline'],12700)
  self.now=12701;self.assertIsNone(self.store.claim(self.c))
  with self.assertRaises(Refused):self.store.submit(self.c,self.candidate,config()['tasks'],1,'late')
  self.store.control(self.c,'pause','p');self.store.control(self.c,'resume','r')
  self.assertEqual(Store(self.store.path,clock=lambda:self.now).status(self.c)['state'],'closing')
  self.now=13601
  with self.assertRaises(Refused):self.store.reserve(self.c,'lease','late',1,'report')
 def test_blank_boolean_negative_are_not_unlimited(self):
  for field in ['maxRounds','maxTrials','softTokenLimit','trialTimeSeconds']:
   for bad in ['',False,-1,0]:
    with self.assertRaises(Refused):self.store.create({**config(),field:bad},field+str(bad))
  with self.assertRaises(Refused):self.store.create({**config(),'wallTimeSeconds':None},'no-time')
 def test_finite_cap_edit_does_not_reset_usage_or_counts(self):
  self.store.submit(self.c,self.candidate,config()['tasks'],3,'b');self.store.claim(self.c)
  self.store.reserve(self.c,'lease','spent',300000,'solver');self.store.settle(self.c,'lease','spent',400000,False)
  self.store.control(self.c,'limits','limit',changes={'softTokenLimit':500000,'reserveTokens':100000,'maxRounds':1})
  with self.assertRaises(Refused):self.store.reserve(self.c,'lease','denied',1,'solver')
  self.assertEqual(self.store.status(self.c)['counts']['rounds'],1)

class ReadingTests(unittest.TestCase):
 def tables(self,contexts=None):
  cs=[{'id':'candidate-11111111-1111-1111-1111-111111111111','bundleId':'a'*64,'plugins':[],'createdAt':0}]
  bs=[{'id':str(i),'round':i,'candidateId':cs[0]['id'],'tasks':['task'],'repeats':1,'state':'finished'} for i in range(1,4)]
  ts=[{'id':'t'+str(i),'batchId':str(i),'task':'task','score':score,'comparisonContext':(contexts or [{'same':1}]*3)[i-1]} for i,score in enumerate([1,0,None],1)]
  return build_tables(cs,bs,ts)
 def test_group_preserves_failed_unscored_and_unlike_conditions_split(self):
  tables=self.tables();self.assertEqual(len(tables['groups']),1);self.assertEqual([x['score'] for x in tables['groups'][0]['results']],[1,0,None])
  self.assertEqual(len(self.tables([{'same':1},{'same':2},{'same':1}])['groups']),3)
  self.assertEqual(len(self.tables([{}, {}, {}])['groups']),3)
 def test_no_machine_ids_in_human_markdown(self):
  tables=self.tables();id=tables['versions'][0]['id']
  self.assertEqual(readable_text('保留 '+id,tables),'保留 H0 · 原始基线')
  text='\n'.join(markdown_tables(tables));self.assertNotIn(id,text);self.assertNotIn('a'*64,text)
 def test_structured_contribution_rejects_unrelated_evidence(self):
  with tempfile.TemporaryDirectory() as root:
   store=Store(Path(root)/'db');cid=store.create(config(),'c')['id'];reports=Reports(store,root)
   a={'summary':'test','observations':[],'hypotheses':[],'limitations':[],'decision':'wait','evidenceRefs':[],
       'process':['做了检查'],'problems':[],'pluginContributions':[{'plugin':'插件','expected':'检查','observed':'未观察','comparison':'无','assessment':'未知','evidenceRefs':['other']}]}
   with self.assertRaises(Refused):reports.save(cid,a)
   a['pluginContributions'][0]['evidenceRefs']=[];r=reports.save(cid,a)
   self.assertEqual(r['reading']['process'],['做了检查']);self.assertEqual(r['analysis']['process'],['做了检查'])

class SourceInspectionTests(unittest.TestCase):
 def test_exact_frozen_source_path_guard_and_no_draft_fallback(self):
  from src.reporting.tables import plugin_key
  with tempfile.TemporaryDirectory() as temp:
   data=Path(temp);store=Store(data/'db');cid=store.create(config(),'c')['id']
   draft=data/'draft';draft.mkdir()
   (draft/'plugin.json').write_text(json.dumps({'schemaVersion':1,'name':'echo','version':'1.0.0','entry':'index.mjs','purpose':'Fixture','configSchema':{'type':'object'},'dependencies':[],'observes':['tool-results'],'intervenes':['tool-results'],'capabilities':['tools'],'fallbackBehavior':'propagate','assets':[]}))
   (draft/'index.mjs').write_text((ROOT/'knowledge/plugin-sdk/examples/echo.mjs').read_text())
   bundle=freeze(ROOT,data/'objects/sha256',json.loads((ROOT/'recipes/h0-sol.json').read_text()),[{'path':str(draft),'config':{}}])
   candidate=store.candidate(cid,bundle,'echo');svc=SimpleNamespace(store=store,data=data)
   key=plugin_key(candidate['plugins'][0]);info=plugin_source(svc,candidate['id'],key)
   self.assertIn('plugin.json',info['files']);self.assertTrue(info['readOnly'])
   self.assertIn('name',plugin_source(svc,candidate['id'],key,'plugin.json')['content'])
   with self.assertRaises(Refused):plugin_source(svc,candidate['id'],key,'../../user-token')
   with self.assertRaises(Refused):plugin_source(svc,candidate['id'],'other','index.mjs')
   with patch('src.control.inspection.subprocess.run') as run,patch('src.control.inspection.sys.platform','darwin'):
    open_folder(info['directory']);self.assertEqual(run.call_args.args[0],['open','--',info['directory']])
