"""Opt-in real Meta development and official Harbor acceptance in a fresh data root.

Requires explicitly supplied authorized model settings. No fixtures choose Meta's
candidate implementation, bypass its tools, or manufacture official feedback.
"""
import argparse,json,signal,socket,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import uvicorn
from src.control.service import ControlService
from src.control.server import make_app
from src.control.meta import MetaDriver


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--quantum-harbor',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--prior-failure',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    authorized=json.loads(args.config.read_text());tasks=['time_budgeted_hamlearn_10q','time_budgeted_shadow_surrogate_60q']
    assert set(tasks)<=set(authorized['tasks'])
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    service=ControlService(ROOT,args.output/'control',args.quantum_harbor,f'http://127.0.0.1:{port}')
    objective='''验收目标：自主修改完整执行 Harness，提高固定 Solver 的任务表现和可恢复性，并通过真实 Quantum Harbor 官方评分完成闭环。先阅读 /work/analysis/prior-failure/ 中真实启动测试的失败摘要和轨迹；这是其他独立验收运行的诊断材料，不能纳入本活动的科学对照统计。请找出默认候选终止的原因，自主设计可复用的修复，复制 /work/plugins/h0 为新完整工程，用原生文件/终端工具修改，通过 candidate_check 和 candidate_freeze 冻结。不要仅写建议，也不要修改平台。
本轮验收范围为两个任务 × H0 与一个改进候选 × 每任务每候选两次独立重复，总计八次正式 Trial。使用用户固定 Solver，选择 parallelism=2，交错安排两候选，相同外部条件。测试仍按 benchmark 完整阶段时限运行，全部失败保留。通过 batch_submit 真正测试并读取 evidence_list / batch_status / results_compare 的官方评分与轨迹；科学零分仍是有效实验结果，不要修改计分规则。判断恢复、工具与上下文改动是否实际生效，区分运行验收和科学收益。完成后保存中文报告，说明每次正式评分、所有失败、改动局限，保留合适版本并 export_create。不要额外扩展为无限轮科学优化。'''
    cfg={k:authorized[k] for k in ('solver','meta')}
    cfg.update(tasks=tasks,concurrency=2,wallTimeSeconds=43200,maxTrials=8,maxRounds=None,objective=objective,
               trialTimeSeconds=None,modelAccessPolicy='control-only-v1',resourcePolicy='meta-resource-planning-v1')
    campaign=service.create(cfg,'real-process-acceptance')['id']
    (args.output/'activity.json').write_text(json.dumps({'campaignId':campaign,'baseURL':service.base_url,'sourceCommit':__import__('subprocess').check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()},indent=2))
    work=service.data/'campaigns'/campaign/'meta-work/analysis/prior-failure';work.mkdir(parents=True)
    # Preserve complete failure evidence with explicit source, never import its score as a new Trial.
    import shutil,hashlib
    paths=[args.prior_failure/'summary.json']
    paths+=list(args.prior_failure.glob('harbor/*/phyexp/events.json'))
    paths+=list(args.prior_failure.glob('harbor/*/phyexp/eventscandidate-outputjson'))
    paths+=list(args.prior_failure.glob('harbor/*/phyexp/candidate.stderr'))
    for source in paths:
        shutil.copyfile(source,work/source.name)
    (work/'sources.json').write_text(json.dumps([{'path':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in paths],indent=2))
    server=uvicorn.Server(uvicorn.Config(make_app(service,supervise=False),log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    service.meta_driver=MetaDriver(service)
    start=time.time();stop=False
    def interrupt(*_):
        nonlocal stop;stop=True
    signal.signal(signal.SIGTERM,interrupt)
    try:
        while not service.store.list('candidates',campaign):
            failed=[o for o in service.store.list('operations',campaign) if o['state']=='failed']
            if failed:raise RuntimeError(json.dumps(failed))
            if time.time()-start>1800:raise TimeoutError('Preparation did not finish')
            time.sleep(.5)
        service.control(campaign,'start','start-acceptance')
        while not stop:
            service.tick()
            c=service.store.get('campaigns',campaign);trials=service.store.list('trials',campaign)
            state={'campaignId':campaign,'state':c['state'],'trials':[{k:t.get(k) for k in ('id','candidateId','task','state','score','execution','scoringStatus','lastCollectionError')} for t in trials],
                   'candidates':[{k:r.get(k) for k in ('id','bundleId','description','project')} for r in service.store.list('candidates',campaign)],
                   'metaSessions':[{k:r.get(k) for k in ('id','state','failure','output')} for r in service.store.list('meta_sessions',campaign)],
                   'exports':service.store.list('exports',campaign)}
            temp=args.output/'status.tmp';temp.write_text(json.dumps(state,ensure_ascii=False,indent=2));temp.replace(args.output/'status.json')
            if c['state'] in ('finished','failed'):
                (args.output/'completed.json').write_text(json.dumps(state,ensure_ascii=False,indent=2));break
            if time.time()-start>cfg['wallTimeSeconds']+600:raise TimeoutError('Acceptance activity exceeded its bound')
            time.sleep(1)
    finally:
        if stop:service.control(campaign,'pause','acceptance-interrupted')
        server.should_exit=True;thread.join(10)
        service.pool.shutdown(wait=True)

if __name__=='__main__':main()
