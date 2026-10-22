"""Synthetic multi-task evolution through real persistence/API/Studio; no model calls."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.control.service import ControlService
from src.control.server import make_app
from src.execution.bundle.freeze import freeze
from src.reporting.tables import plugin_key
import uvicorn

def seed(service):
    store=service.store;now=time.time();tasks=['time_budgeted_hamlearn_10q','logical_cnot_decoder_calibration']
    model={'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'}
    cfg={'name':'进化解释 E2E · 合成阅读场景','fixture':True,'solver':model,'meta':model,'tasks':tasks,'wallTimeSeconds':7200,'concurrency':2,'maxTrials':20,'maxRounds':8}
    c=store.create(cfg,'evolution-ui')['id']
    if store.list('research_records',c):return c
    old=store.create({**cfg,'name':'先前研究 · 合成历史来源'},'history-ui')['id']
    evidence=service.evidence.add(old,None,'trajectory','合成轨迹：工具连续返回同一参数错误；重复调用并没有改变输入。\n'+('上下文记录，仅供工程检查。\n'*1500),{'archive':'events.txt'})
    adopted=service.adoptions.adopt(c,old,'evidence',evidence['id'],'研究输入不变时的重复错误提示是否可改善行动。','meta-research','adopt-ui')
    store.control(c,'start','start-ui')
    anchor={'evidenceId':adopted['evidenceId'],'sha256':adopted['sha256'],'start':0,'end':33,'unit':'characters','supports':'只说明先前轨迹存在重复参数错误，不证明提示能改善成功率。'}
    record={'kind':'motivation','state':'proposed','summary':'先让重复错误变得可识别，再验证 Solver 是否调整行动。','problem':'先前活动中，同一参数错误重复出现。','hypothesis':'保留完整错误并给出简短分类，可能有助于修正输入。','change':'尝试通用错误摘要，不替 Solver 提交科学答案。','validation':'分别核对加载、适用、触发、行为和任务结果。','limitations':['合成工程数据，不能说明科学收益'],'nextStep':'验证参数错误出现时的行为；实验是否受理以账本为准。','factAt':now,'anchors':[anchor]}
    r=service.research.save(c,record,0,'motivation-ui');ref={'recordId':r['recordId'],'revision':1}
    recipe=json.loads((ROOT/'recipes/h0-sol.json').read_text());bundles=[]
    for index in range(3):
        plugins=[]
        if index:
            draft=service.data/f'fixture-plugin-{index}';draft.mkdir(exist_ok=True)
            (draft/'plugin.json').write_text(json.dumps({'schemaVersion':1,'name':'readable-errors','version':'1.0.0','entry':'index.mjs','displayName':'可读错误提示','functionSummary':'保留原件并提示重复错误','mechanism':'合成插件只用于界面与关联检查','purpose':'UI fixture','configSchema':{'type':'object'},'dependencies':[],'observes':['tool-results'],'intervenes':['tool-results'],'capabilities':['tools'],'fallbackBehavior':'propagate','assets':[]}))
            (draft/'index.mjs').write_text((ROOT/'knowledge/plugin-sdk/examples/echo.mjs').read_text()+f'\n// fixture revision {index}\n')
            plugins=[{'path':str(draft),'config':{}}]
        bundle=freeze(ROOT,service.data/'objects/sha256',recipe,plugins)
        candidate=store.candidate(c,bundle,['固定基线','保留完整错误的提示方案','调整后的候选，尚未完成验证'][index],bundles[0]['id'] if bundles else None,{'status':'passed','fixture':True},research_refs=[ref] if index else None)
        bundles.append(candidate)
    batches=[];last_ev=None
    for index,version in enumerate(bundles):
        batch=store.submit(c,version['id'],tasks,2 if index<2 else 1,'batch-ui-'+str(index));batches.append(batch)
        trials=[t for t in store.list('trials',c) if t['batchId']==batch['id']]
        for j,t in enumerate(trials):
            if index==2:
                if j==0:store.trial_update(t['id'],state='running',startedAt=now-45)
                continue
            score=1 if index==1 or j%2 else 0
            store.trial_update(t['id'],state='finished',score=score,startedAt=now-180,finishedAt=now-90,scoringStatus='completed',comparisonContext={'taskSourcesDigest':'fixture-source','runnerImageId':'fixture-image','verifierImageId':'fixture-verifier'},taskTimeLimitSeconds=600)
            last_ev=service.evidence.add(c,t['id'],'trajectory','合成实验：插件已加载；本次没有出现重复错误。未知机制收益。',{'archive':'events.txt'})
    for batch in batches[:2]:
        refs=[e['id'] for e in store.list('evidence',c) if any(t['id']==e['trialId'] and t['batchId']==batch['id'] for t in store.list('trials',c))]
        service.reports.save(c,{'summary':'合成本轮观察','brief':'本轮已结束；结果不证明插件收益。','observations':[],'hypotheses':[],'limitations':['合成工程数据'],'decision':'继续检验','evidenceRefs':refs,'researchRefs':[ref]},batch['id'])
    current=service.research.save(c,{**record,'kind':'observation','state':'inconclusive','summary':'候选完成了本轮任务，但重复错误机制尚未得到检验。','candidateIds':[bundles[1]['id']],'plugins':[{'candidateId':bundles[1]['id'],'pluginKey':plugin_key(bundles[1]['plugins'][0])}],'batchIds':[batches[1]['id']],'anchors':[anchor],'limitations':['每项任务只有两次合成尝试','成功不证明错误提示被触发']},1,'observed-ui',r['recordId'])
    selection=store.retain(c,bundles[1]['id'],'保留候选便于继续验证完整错误提示。',[last_ev['id']],summary='暂时保留 H1；任务结果已有记录，机制收益仍未知。',tradeoffs='提示增加输出，需要核对是否影响阅读。',limitations=['合成数据，不做因果结论'],reconsiderWhen='复测出现退步或摘要遮蔽错误细节',alternatives=[{'candidateId':bundles[0]['id'],'reason':'作为固定基线保留；当前选择不抹去它。','evidenceRefs':[]},{'candidateId':bundles[2]['id'],'reason':'实验尚在运行和排队，暂不选。','evidenceRefs':[]}],researchRefs=[{'recordId':r['recordId'],'revision':2}],expectedSelectionRevision=0)
    report=service.reports.save(c,{'summary':'这是合成工程场景，用于验证从问题来源到选择的阅读路径。','brief':'H1 结果已记录，错误提示的实际贡献仍需验证。','observations':['官方评分与解释分开保存'],'hypotheses':['需要出现对应条件的对照实验'],'limitations':['合成数据，不是科学实验'],'decision':'暂保留 H1','evidenceRefs':[last_ev['id']],'researchRefs':[{'recordId':r['recordId'],'revision':2}]})
    service.research.save(c,{**record,'kind':'turning_point','state':'testing','summary':'后续转折：将下一步重点改为验证触发条件。','reportIds':[report['id']],'decisionIds':[selection['selectionDecision']['id']]},2,'turning-ui',r['recordId'])
    return c

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--port',type=int,default=18562);args=p.parse_args()
    service=ControlService(ROOT,args.data_dir,ROOT.parent/'Quantum-Harbor',f'http://127.0.0.1:{args.port}')
    print(json.dumps({'campaignId':seed(service),'fixture':True,'modelRequests':0}),flush=True)
    uvicorn.run(make_app(service,supervise=False),host='127.0.0.1',port=args.port,log_level='warning')
