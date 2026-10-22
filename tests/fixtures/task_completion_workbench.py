"""Synthetic v4/legacy outcomes in the real workbench; no execution or model calls."""
import argparse
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from src.control.service import ControlService
from src.control.server import make_app
from src.execution.host.failure import public_failure
import uvicorn

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser()
parser.add_argument('--data-dir',type=Path,required=True)
parser.add_argument('--port',type=int,default=18552)
args=parser.parse_args()
service=ControlService(ROOT,args.data_dir,ROOT.parent/'Quantum-Harbor',f'http://127.0.0.1:{args.port}')
task='time_budgeted_hamlearn_10q'
now=time.time()
for rule,name in [('task-completion-v4','v4 计分验证（模拟数据）'),('task-completion-v3','v3 历史口径（模拟数据）')]:
    c=service.store.create({'name':name,'taskEvaluationRule':rule,
        'meta':{'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'},
        'solver':{'provider':'openai-codex','model':'gpt-6-sol','reasoningEffort':'medium'},
        'tasks':[task],'concurrency':1,'wallTimeSeconds':3600},rule)
    if service.store.list('trials',c['id']):continue
    service.store.control(c['id'],'start','start')
    candidate=service.store.candidate(c['id'],{'id':'synthetic-'+rule,'path':'/fixture/no-execution','plugins':[]},'H0',check={'status':'passed'})
    service.store.submit(c['id'],candidate['id'],[task],7,'batch')
    cases=[(1,None,'finished',True),(None,'verifier_failed','failed',True),(None,'container_transport_error','failed',True),
           (None,None,'finished',True),(None,'supervisor_lost_start_not_repeated','unknown',True),
           (None,'user_stop','cancelled',True),(None,'budget_admission_denied','cancelled',False)]
    for row,(score,code,state,started) in zip(service.store.list('trials',c['id']),cases):
        service.store.trial_update(row['id'],score=score,state=state,startedAt=now-90 if started else None,finishedAt=now-30,
            stopReason=code,failure=public_failure({'code':code,'source':'controller','stage':'verifier' if code=='verifier_failed' else 'execution'}) if code else None,
            scoringStatus='completed' if score is not None else 'failed' if code=='verifier_failed' else 'not_run')
    service.reports.status_summary(c['id'],'模拟数据，用于计分界面验证')
    c=service.store.get('campaigns',c['id']);c.update(state='finished',explorationClosed=True,finishedAt=now-20)
    service.store.put('campaigns',c)
uvicorn.run(make_app(service,supervise=False),host='127.0.0.1',port=args.port,log_level='warning')
