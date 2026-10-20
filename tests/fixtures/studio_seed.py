"""Seed an isolated UI fixture store. No runners, models, or scientific experiments."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.control.store import Store
from src.evidence.library import EvidenceLibrary
from src.reporting.reports import Reports
from src.execution.bundle.freeze import freeze

parser = argparse.ArgumentParser()
parser.add_argument('--data-dir', type=Path, required=True)
args = parser.parse_args()
data = args.data_dir.resolve()
store = Store(data/'control.sqlite')
model = {'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
config = {'name':'UI 检查夹具 · 非科学实验','fixture':True,'solver':model,'meta':model,
          'tasks':['time_budgeted_hamlearn_10q'],'wallTimeSeconds':7200,'concurrency':1,
          'maxRounds':8,'maxTrials':8,'softTokenLimit':300000,'reserveSeconds':300,'reserveTokens':30000}
campaign = store.create(config, 'studio-fixture-'+str(time.time_ns()))['id']
recipe = json.loads((ROOT/'recipes/h0-sol.json').read_text())
base = freeze(ROOT,data/'objects/sha256',recipe,[])
h0 = store.candidate(campaign,base,'UI 夹具基线',check={'status':'passed','fixture':True})
draft = data/'studio-plugin';draft.mkdir(exist_ok=True)
(draft/'plugin.json').write_text(json.dumps({'schemaVersion':1,'name':'studio-echo','version':'1.0.0','entry':'index.mjs',
    'purpose':'仅用于 UI 验证的回显插件','configSchema':{'type':'object'},'dependencies':[],
    'observes':['tool-results'],'intervenes':['tool-results'],'capabilities':['tools'],
    'fallbackBehavior':'propagate','assets':[]},ensure_ascii=False))
(draft/'index.mjs').write_text((ROOT/'knowledge/plugin-sdk/examples/echo.mjs').read_text())
bundle = freeze(ROOT,data/'objects/sha256',recipe,[{'path':str(draft),'config':{}}])
version = store.candidate(campaign,bundle,'带源码的 UI 夹具',parent=h0['id'],check={'status':'passed','fixture':True})
store.control(campaign,'start','fixture-start')  # Store only: never invokes a runner.
library = EvidenceLibrary(store,data);reports=Reports(store,data)
for index, candidate in enumerate([h0,version,version]):
    batch=store.submit(campaign,candidate['id'],config['tasks'],1,'fixture-round-'+str(index))
    trial=store.claim(campaign)
    store.trial_update(trial['id'],state='failed' if index==2 else 'finished',score=None if index==2 else index,
                       finishedAt=time.time(),scoringStatus='not_run' if index==2 else 'completed',
                       failure={'stage':'model','source':'controller','code':'fixture_stream_lost',
                                'message':'UI 合成断流记录，未调用模型'} if index==2 else None,
                       comparisonContext={'fixture':True,'sameEnvironment':'studio'})
    ev=library.add(campaign,trial['id'],'trajectory',('UI 合成证据，非真实科学轨迹。\n'*1800),{'fixture':True})
    reports.save(campaign,{'summary':'UI 夹具：结果与故障分开记录','observations':['此处只有合成数据'],
         'hypotheses':[],'limitations':['未运行真实模型和官方科学实验'],'decision':'仅供界面检查',
         'process':['读取合成记录并检查页面关联'],'problems':['第 3 轮模拟外部故障'],
         'evidenceRefs':[ev['id']]},batch['id'],author='fixture')
store.reserve(campaign,'fixture-lease','fixture-unknown',2000,'solver')
store.settle(campaign,'fixture-lease','fixture-unknown',None,True)
(data/'studio-fixture.json').write_text(json.dumps({'campaignId':campaign,'candidateId':version['id']},indent=2))
print(json.dumps({'campaignId':campaign,'fixture':True,'modelRequests':0}))
