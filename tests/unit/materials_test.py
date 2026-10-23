import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.control.service import ControlService
from src.control.store import Refused, encoded
from src.control.defaults import DEFAULT_OBJECTIVE
from src.control.meta_context import startup_context, system_prompt
from src.control.meta import MetaDriver
from src.evidence.library import feedback
from src.evidence.materials import snapshot_tasks
from src.execution.bundle.freeze import freeze

ROOT = Path(__file__).resolve().parents[2]
TASK = 'time_budgeted_hamlearn_10q'
MODEL = {'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}


class MaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.quantum = self.root/'quantum'
        folder = self.quantum/'harbor_tasks'/TASK
        folder.mkdir(parents=True)
        (folder/'task.toml').write_text('[agent]\ntimeout_sec = 3600\n')
        (folder/'instruction.md').write_text('公开任务：保留原始材料。\n' + '长文本'*12000 + '\n末尾查询锚点。')
        (folder/'hidden.json').write_text('SECRET_NOT_FOR_META')
        self.service = ControlService(ROOT,self.root/'data',self.quantum,'http://127.0.0.1:1')
        self.config = {'solver':MODEL,'meta':{**MODEL,'model':'gpt-6-astra'},'tasks':[TASK],
                       'wallTimeSeconds':7200,'concurrency':1,'metaCompositionConfig':json.loads((ROOT/'packages/meta-harness/composition.json').read_text())}
        with patch.object(self.service,'_operation',return_value={'fixture':True}):
            self.c = self.service.create(self.config,'new')['id']
        self.store = self.service.store
        self.store.control(self.c,'start','start')
        self.materials = self.service.materials

    def tearDown(self):
        self.service.pool.shutdown(wait=True)
        self.temp.cleanup()

    def test_task_catalog_and_new_activity_freeze_the_same_benchmark_limits(self):
        task=next(t for t in self.service.task_catalog()['tasks'] if t['id']==TASK)
        self.assertEqual(task['solverTimeSeconds'],3600)
        config=self.store.get('campaigns',self.c)['config']
        self.assertEqual(config['executionTimePolicy']['version'],'benchmark-time-v1')
        frozen=json.loads((self.service.data/'meta-compositions'/config['metaComposition']['id']/'manifest.json').read_text())
        self.assertEqual(frozen['systemPrompt']['version'],'meta-system-v9')
        self.assertEqual(config['stopPolicy'],'goal-or-budget-v1')
        self.assertNotIn('benchmark 原始配置',frozen['systemPrompt']['text'])
        self.assertNotIn('trial_conditions_accept',frozen['systemPrompt']['text'])
        self.assertEqual(config['taskTimeLimits'][TASK],{k:v for k,v in task.items() if k!='id'})
        (self.quantum/'harbor_tasks'/TASK/'task.toml').write_text('[agent]\ntimeout_sec=1800\n')
        with patch.object(self.service,'_operation',return_value={}):
            self.assertEqual(self.service.create(self.config,'new')['config']['taskTimeLimits'],config['taskTimeLimits'])
        with self.assertRaisesRegex(ValueError,'changed'):self.service._verify_task_images(config)
        for changes in [{'trialTimeSeconds':1200},{'resourcePolicy':None},{'executionTimePolicy':{}}]:
            with self.assertRaises(Refused):self.service.create({**self.config,**changes},'invalid')

    def test_default_blank_and_custom_goals_without_history_rewrite(self):
        self.assertEqual(self.store.get('campaigns',self.c)['config']['objective'],DEFAULT_OBJECTIVE)
        for value in [None,'',' \n ']:
            c=self.store.create({**self.config,'objective':value},'blank'+str(value))
            self.assertEqual(c['config']['objective'],DEFAULT_OBJECTIVE)
        custom='研究 {{Solver配置}} 的可复用机制'
        c=self.store.create({**self.config,'objective':custom},'custom')
        before=encoded(self.store.list('campaigns'))
        self.assertEqual(self.store.create({**self.config,'objective':custom},'custom',defaults={'new':True}),c)
        self.assertEqual(encoded(self.store.list('campaigns')),before)
        text=system_prompt(c['config'])['text']
        self.assertIn(custom,text)
        self.assertIn('固定 Solver：\n{"model": "gpt-6-sol"',text)
        self.assertNotIn('gpt-6-astra',text)
        self.assertNotIn('至少一个',text)

    def test_startup_has_navigation_and_live_state_not_entire_history(self):
        before=startup_context(self.service,self.c)
        self.store.put('reports',{'id':'report-big','campaignId':self.c,'analysis':'HISTORY_SENTINEL'*10000})
        after=startup_context(self.service,self.c)
        self.assertEqual(set(before),set(after))
        self.assertNotIn('HISTORY_SENTINEL',encoded(after))
        self.assertLess(len(encoded(after)),6000)
        self.assertIn('materials_search',after['materials']['tools'])
        self.assertEqual(after['state']['solver'],MODEL)

    def test_plugin_guides_are_readable_through_meta_sdk_and_materials(self):
        declared=self.service.meta_call(self.c,'sdk_inspect',{'name':'agent/request-error'})
        self.assertEqual(declared['availability'],'declared-in-execution-sdk')
        declaration=self.service.meta_call(self.c,'sdk_read',{'id':declared['document'],'limit':32000})
        self.assertIn('agent/request-error',declaration['text'])
        for name in ['README.md','plugin-design.md','tools.md','subagents.md','request-recovery.md','resource-planning.md']:
            id='guides/'+name
            item=self.service.meta_call(self.c,'sdk_read',{'id':id})
            self.assertEqual(item['text'],(ROOT/'knowledge/plugin-sdk'/id).read_text())
            self.assertEqual(item['source'],'knowledge/plugin-sdk/'+id)
            self.assertEqual(item['sha256'],hashlib.sha256(item['text'].encode()).hexdigest())
            self.assertEqual(self.materials.read(self.c,f'sdk:{item["packId"]}:{id}')['text'],item['text'])
        index=self.service.meta_call(self.c,'sdk_read',{'id':'guides/README.md'})
        for target in re.findall(r'\]\(([^)]+\.md)\)',index['text']):
            self.service.meta_call(self.c,'sdk_read',{'id':'guides/'+target})
        matches=self.service.meta_call(self.c,'sdk_search',{'query':'任务委派'})['matches']
        self.assertIn('guides/subagents.md',[m['id'] for m in matches])
        self.assertIn('guides/README.md',system_prompt(self.config)['text'])
        self.assertRaises(ValueError,self.service.meta_call,self.c,'sdk_read',{'id':'guides/../../AGENTS.md'})

    def test_old_pack_without_guides_keeps_its_overview_and_does_not_fallback(self):
        original=self.service.knowledge_for(self.c)
        manifest=json.loads(json.dumps(original.manifest))
        manifest['documents']={k:v for k,v in manifest['documents'].items() if not k.startswith('guides/')}
        manifest.pop('id')
        manifest['id']=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
        archived=self.service.data/'knowledge-packs'/manifest['id']
        shutil.copytree(original.path,archived)
        shutil.rmtree(archived/'guides')
        (archived/'manifest.json').write_text(json.dumps(manifest))
        c=self.store.get('campaigns',self.c)
        c['config']['knowledgePackId']=manifest['id'];self.store.put('campaigns',c)
        item=self.service.meta_call(self.c,'sdk_read',{'id':'overview'})
        self.assertEqual(item['packId'],manifest['id'])
        self.assertEqual(item['text'],original.read('overview')['text'])
        self.assertRaises(ValueError,self.service.meta_call,self.c,'sdk_read',{'id':'guides/README.md'})

    def test_driver_archives_rendered_prompt_on_each_new_session_without_model_call(self):
        driver=MetaDriver(self.service)
        with patch('src.control.meta.subprocess.Popen') as process:
            process.return_value.pid=123
            driver.start(self.c)
            driver.start(self.c)
            self.assertEqual(len(self.store.list('meta_sessions',self.c)),1)
            row=self.store.list('meta_sessions',self.c)[0];row['state']='interrupted';self.store.put('meta_sessions',row)
            driver.start(self.c)
        rows=self.store.list('meta_sessions',self.c)
        self.assertEqual(len(rows),2)
        for row in rows:
            config=json.loads((Path(row['output'])/'context.json').read_text())
            self.assertEqual(config['systemPrompt']['sha256'],row['systemPromptSha256'])
            self.assertIn(DEFAULT_OBJECTIVE,config['systemPrompt']['text'])
            self.assertEqual(json.loads(config['prompt'])['state']['solver'],MODEL)
            self.assertNotIn('candidates',json.loads(config['prompt']))

    def test_public_task_snapshot_search_tail_pagination_and_immutability(self):
        ref='task:'+TASK
        initial=self.materials.read(self.c,ref)
        (self.quantum/'harbor_tasks'/TASK/'instruction.md').write_text('changed')
        snapshot_tasks(self.service,self.c)
        self.assertEqual(self.materials.read(self.c,ref)['sha256'],initial['sha256'])
        match=self.materials.search(self.c,'末尾查询锚点',kind='task')['matches'][0]
        self.assertGreater(match['matchOffset'],32000)
        self.assertIn('末尾查询锚点',self.materials.read(self.c,ref,offset=match['offset'])['text'])
        self.assertEqual(self.materials.search(self.c,'SECRET_NOT_FOR_META',kind='task')['matches'],[])
        self.assertRaises(Refused,self.materials.read,self.c,'task:../../hidden.json')
        for offset,limit in [(-1,10),(True,10),(0,32001)]:
            self.assertRaises(Refused,self.materials.read,self.c,ref,offset,limit)
        page=self.materials.list(self.c,kind='sdk',limit=2)
        self.assertEqual(len(page['items']),2)
        self.assertEqual(page['nextOffset'],2)

    def test_symlink_task_is_unavailable_and_cannot_read_host(self):
        original=self.quantum/'harbor_tasks'/TASK/'instruction.md'
        original.unlink();original.symlink_to(self.quantum/'harbor_tasks'/TASK/'hidden.json')
        other=self.store.create(self.config,'other')['id']
        snapshot_tasks(self.service,other)
        item=self.materials.read(other,'task:'+TASK)
        self.assertEqual(item['availability'],'unavailable')
        self.assertNotIn('SECRET',encoded(item))

    def test_sdk_is_pinned_and_tampering_or_missing_pack_does_not_fallback(self):
        id=self.store.get('campaigns',self.c)['config']['knowledgePackId']
        self.assertEqual(self.service.knowledge_for(self.c).manifest['id'],id)
        copy=self.root/'alternate';shutil.copytree(self.service.knowledge.path,copy)
        (copy/'overview.txt').write_text('wrong')
        file=self.service.data/'knowledge-packs'/id/'overview.txt'
        file.write_text('tampered')
        self.assertRaises(Refused,self.materials.read,self.c,f'sdk:{id}:overview')
        c=self.store.get('campaigns',self.c);c['config']['knowledgePackId']='0'*64;self.store.put('campaigns',c)
        self.assertRaises(Refused,self.service.knowledge_for,self.c)

    def add_version(self):
        draft=self.root/'draft';draft.mkdir()
        manifest={'schemaVersion':1,'name':'fixture','version':'1','entry':'index.mjs','purpose':'测试用途',
            'configSchema':{'type':'object'},'dependencies':[],'observes':[],'intervenes':[],
            'capabilities':['public-context'],'fallbackBehavior':'none','assets':[]}
        (draft/'plugin.json').write_text(json.dumps(manifest))
        (draft/'index.mjs').write_text('export const name="frozen-fixture";')
        bundle=freeze(ROOT,self.service.data/'objects/sha256',json.loads((ROOT/'recipes/h0-sol.json').read_text()),
                      [{'path':draft}],self.service.knowledge.manifest)
        c=self.store.candidate(self.c,bundle,'中文版本说明',check={'status':'passed'})
        (draft/'index.mjs').write_text('changed draft')
        self.store.update_plan(self.c,{'parallelism':1,'closeoutReserveSeconds':0,'closeoutReserveTokens':0},'Fixture execution plan','plan',0,source='operator')
        batch=self.store.submit(self.c,c['id'],[TASK],1,'batch')
        return c,batch

    def test_versions_sources_experiments_and_analysis_link_to_frozen_records(self):
        c,b=self.add_version()
        row=self.materials.list(self.c,kind='plugin',candidateId=c['id'])['items']
        code=next(r for r in row if r['title'].endswith('index.mjs'))
        self.assertIn('frozen-fixture',self.materials.read(self.c,code['ref'])['text'])
        version=json.loads(self.materials.read(self.c,'version:'+c['id'])['text'])
        self.assertEqual(version['recipe']['model'],'gpt-6-sol')
        experiment=json.loads(self.materials.read(self.c,'experiment:'+b['id'])['text'])
        self.assertEqual(experiment['trials'][0]['score'],None)
        trial=self.store.list('trials',self.c)[0]
        safe=feedback(TASK,{'reward_binary':0,'secret':'SECRET_NOT_FOR_META'})
        e=self.service.evidence.add(self.c,trial['id'],'official-result',encoded(safe),{'archive':'summary.json'})
        a={'summary':'模型假设：还不能确认插件收益','observations':[],'hypotheses':['假设'],
           'limitations':['样本不足'],'decision':'继续','evidenceRefs':[e['id']]}
        r=self.service.reports.save(self.c,a,b['id'])
        read=self.materials.read(self.c,'analysis:'+r['id'])
        self.assertEqual(read['source']['classification'],'model-analysis')
        self.assertIn(e['id'],read['text'])
        self.assertNotIn('markdownPath',read['text'])
        self.assertEqual(len(self.materials.list(self.c,kind='analysis',candidateId=c['id'])['items']),1)
        self.assertEqual(len(self.materials.list(self.c,kind='evidence',task=TASK,batchId=b['id'])['items']),1)
        self.assertEqual(self.materials.search(self.c,'SECRET_NOT_FOR_META')['matches'],[])
        other=self.store.create(self.config,'other')['id']
        for ref in [code['ref'],'version:'+c['id'],'experiment:'+b['id'],'analysis:'+r['id'],'evidence:'+e['id']]:
            self.assertRaises(Refused,self.materials.read,other,ref)
        self.assertRaises(Refused,self.materials.list,other,candidateId=c['id'])

    def test_legacy_missing_instruction_never_uses_current_checkout(self):
        c=self.store.create(self.config,'legacy')['id']
        item=self.materials.list(c,kind='task')['items'][0]
        self.assertEqual(item['availability'],'unavailable')
        self.assertNotIn('text',self.materials.read(c,item['ref']))

    def test_meta_finish_reason_is_persisted_without_claiming_verified_success(self):
        self.assertRaises(Refused,self.service.meta_call,self.c,'campaign_finish',{})
        self.assertRaises(Refused,self.service.meta_call,self.c,'campaign_finish',{'reason':'No independent review'})
        legacy=self.store.create(self.config,'legacy-finish')['id'];self.store.control(legacy,'start','start')
        result=self.service.meta_call(legacy,'campaign_finish',{'reason':'已有尝试显示当前方向收益有限；仍有剩余预算，稳定性未证实。'})
        self.assertEqual(result['finishAssessment']['source'],'meta-analysis')
        self.assertEqual(result['stopReason'],'meta_finished')
        self.assertEqual(self.store.status(self.c)['counts']['trials'],0)
