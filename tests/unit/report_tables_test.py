import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from src.reporting.tables import build_tables, plugin_key, plugin_changes, config_changes, markdown_tables
from src.reporting.reports import Reports
from src.control.store import Store, Refused


def plugin(name='audit', version='1.0', digest='a', config=None):
    return {'name':name,'version':version,'digest':digest,'config':{} if config is None else config,
            'manifest':{'purpose':'核对结果','intervenes':['systemPrompt.section']}}
def candidate(id,plugins,parent=None,at=0):
    return {'id':id,'bundleId':id,'plugins':plugins,'parentId':parent,'createdAt':at,'description':id}
def batch(id,round,candidate):
    return {'id':id,'round':round,'candidateId':candidate,'tasks':['task'],'repeats':1,'state':'finished','acceptedAt':round*10}

class ReportTablesTests(unittest.TestCase):
    def test_repeats_and_rollback_compare_previous_round_not_parent_or_completion(self):
        cs=[candidate('a',[],at=1),candidate('b',[plugin()],parent='a',at=11),candidate('c',[plugin('other')],parent='a',at=21)]
        bs=[batch('first',1,'a'),batch('second',2,'b'),batch('third',3,'b'),batch('fourth',4,'c'),batch('fifth',5,'a')]
        ts=[{'id':'t','batchId':'third','task':'task','score':None,'finishedAt':1}]
        t=build_tables(cs,list(reversed(bs)),ts)
        self.assertEqual([r['round'] for r in t['rounds']],[1,2,3,4,5])
        self.assertEqual(t['rounds'][2]['changes'][0]['kind'],'unchanged')
        self.assertEqual({x['kind'] for x in t['rounds'][3]['changes']},{'removed','added'})
        self.assertEqual(t['versions'][2]['parentLabel'],'H0')
        self.assertEqual(t['rounds'][3]['previousVersionLabel'],'H1')
        self.assertEqual(t['rounds'][4]['changes'][0]['kind'],'removed')
        self.assertIsNone(t['rounds'][2]['results'][0]['score'])

    def test_plugin_identity_keeps_same_version_different_source_separate(self):
        a,b=plugin(),plugin(digest='b')
        tables=build_tables([candidate('a',[a]),candidate('b',[b],at=1)],[],[])
        self.assertEqual(len(tables['plugins']),2)
        self.assertNotEqual(plugin_key(a),plugin_key(b))
        changes=plugin_changes(candidate('a',[a]),candidate('b',[b]))
        self.assertIn('版本号仍为',changes[0]['label'])

    def test_configuration_null_boolean_order_and_membership_are_precise(self):
        a=plugin(config={'enabled':True,'settings':{'x':None}})
        b=plugin(config={'enabled':False,'settings':{},'new':None})
        changes=plugin_changes(candidate('a',[a]),candidate('b',[b]))
        self.assertEqual(changes[0]['kind'],'configured')
        self.assertEqual({x['kind'] for x in changes[0]['configChanges']},{'changed','removed','added'})
        self.assertTrue(config_changes(True,1))
        other=plugin('other')
        self.assertEqual(plugin_changes(candidate('a',[a,other]),candidate('b',[other,a]))[0]['kind'],'reordered')
        self.assertEqual([d['kind'] for d in plugin_changes(candidate('a',[a]),candidate('b',[other,a]))],['added'])
        self.assertEqual(plugin_changes(candidate('a',[a]),candidate('b',[a]))[0]['kind'],'other')

    def test_round_report_includes_predecessor_and_ancestors_but_not_future(self):
        cs=[candidate('a',[],at=1),candidate('b',[plugin()],parent='a',at=11),candidate('c',[plugin('future')],parent='a',at=31)]
        bs=[batch('first',1,'a'),batch('second',2,'b'),batch('third',3,'c')]
        t=build_tables(cs,bs,[],batch_id='second')
        self.assertEqual([v['label'] for v in t['versions']],['H0','H1'])
        self.assertEqual([r['round'] for r in t['rounds']],[1,2]);self.assertTrue(t['rounds'][-1]['focus'])

    def test_annotation_is_content_bound_and_markdown_does_not_inject(self):
        p=plugin();notes={plugin_key(p):{'displayName':'检查','functionSummary':'建议 <script>x</script> | [bad](https://x)','mechanism':'提示词建议','source':{'label':'源码补充说明','kind':'operator-source-review'}}}
        t=build_tables([candidate('a',[p]),candidate('b',[plugin(digest='b')],at=1)],[],[],annotations=notes)
        self.assertEqual(t['plugins'][0]['displayName'],'检查')
        self.assertEqual(t['plugins'][1]['functionSummary'],'核对结果')
        md='\n'.join(markdown_tables(t));self.assertNotIn('<script>',md);self.assertNotIn('[bad]',md)
        self.assertIn('&#124;',md)

    def test_missing_predecessor_is_not_reported_as_unchanged(self):
        tables=build_tables([candidate('known',[])],[batch('first',1,'missing'),batch('second',2,'known')],[])
        self.assertEqual(tables['rounds'][0]['versionLabel'],'版本缺失')
        self.assertEqual(tables['rounds'][1]['changes'][0]['kind'],'unavailable')

    def test_multiple_tasks_unscored_and_zero_remain_explicit(self):
        b=batch('b',1,'a');b['tasks']=['a','b'];b['repeats']=2
        ts=[{'id':str(i),'batchId':'b','task':task,'repeat':j,'score':score,'state':'finished'} for i,(task,j,score) in enumerate([('a',0,0),('a',1,None),('b',0,1),('b',1,0)])]
        t=build_tables([candidate('a',[])],[b],ts)
        self.assertEqual([r['score'] for r in t['rounds'][0]['results']],[0,None,1,0])
        md='\n'.join(markdown_tables(t));self.assertIn('未评分',md);self.assertIn('2 任务 × 2 次',md)

    def test_display_revision_preserves_old_files_analysis_facts_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db');reports=Reports(store,temp)
            cfg={'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},'tasks':['time_budgeted_hamlearn_10q'],'maxRounds':2,'maxTrials':2,'concurrency':1,'wallTimeSeconds':100,'trialTimeSeconds':30,'softTokenLimit':1000,'reserveSeconds':10,'reserveTokens':100}
            c=store.create(cfg,'key');cid=c['id'];store.candidate(cid,{'id':'base','path':'/none','plugins':[]},'H0')
            store.control(cid,'stop','stop');store.finalize(cid)
            old=reports.status_summary(cid,'尚无科学实验');old.pop('tables');old=store.put('reports',old)
            before=Path(old['markdownPath']).read_bytes();facts=copy.deepcopy(old['facts']);analysis=copy.deepcopy(old['analysis'])
            new=reports.refresh_presentation(old['id'])
            self.assertNotEqual(new['id'],old['id']);self.assertEqual(new['analysis'],analysis);self.assertEqual(new['facts'],facts)
            self.assertEqual(new['factsSha256'],old['factsSha256']);self.assertEqual(Path(old['markdownPath']).read_bytes(),before)
            self.assertEqual(reports.refresh_presentation(new['id'])['id'],new['id'])
            md=Path(new['markdownPath']).read_text()
            for title in ['## 插件表','## 执行版本表','## 实验轮次表']:self.assertIn(title,md)
