"""Opt-in paid-model acceptance in a new isolated directory; never runs in npm test.

Runs an actual H0 before references. The default smoke task changes only the
instruction in an isolated copy; official mode uses the original scientific task.
Both retain the original simulator, task materials, images and official verifier.
The joint scenario delegates selection/submission to the real native Meta model.
"""
import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
import uvicorn
from src.control.service import ControlService
from src.control.server import make_app
from src.control.meta import MetaDriver
from src.control.meta_composition import freeze as freeze_meta
from src.control.reference.policy import DEFAULT,TERMINAL
from src.control.task_images import POLICY
from src.execution.adapters.quantum_harbor.results import verify_manifest
from src.execution.host.single_run import task_image_sources
from src.control.task_images import sources_digest,verify_locks

TASK='time_budgeted_hamlearn_10q'

def write(path,value):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    temporary.chmod(0o600);temporary.replace(path)

def smoke_task(source,output,lock):
    original=task_image_sources(source);target=output/'quantum-smoke'
    for relative in original:
        destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/relative,destination)
    instruction='harbor_tasks/'+TASK+'/instruction.md'
    (target/instruction).write_text('''# Engineering acceptance task — not a scientific benchmark
Use the attached tools for exactly this small check:
1. Call bash (or the task MCP task_bash tool) once with `printf reference-e2e-ok`.
2. Call the qsim list_devices tool once and confirm the device is reachable.
3. Finish with a short report of these two observations.
Do not solve Hamiltonian learning, run measurements, create files, or submit an answer.
The unchanged official verifier should record no_submission and reward 0.
This deliberately tests transport, tool execution, evidence, official grading and accounting only.
''')
    updated=task_image_sources(target)
    assert {name for name in original if original[name]!=updated.get(name)}=={instruction}
    # instruction.md is consumed by Harbor, not copied by any image Dockerfile;
    # all image inputs and all scientific/verifier materials remain byte-identical.
    frozen={**lock,'taskSourcesDigest':sources_digest(updated),'source':'Engineering smoke instruction copy; unchanged pinned simulator/main/verifier images',
        'engineeringFixture':{'changedFiles':[instruction],'originalTaskSourcesDigest':sources_digest(original)}}
    verify_locks(target,[TASK],{TASK:frozen});write(output/'smoke-task-image-lock.json',frozen)
    return target,frozen

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-real-models',action='store_true',required=True)
    parser.add_argument('--scenario',choices=['model','harness','joint'],required=True)
    parser.add_argument('--task-mode',choices=['smoke','official'],default='smoke')
    parser.add_argument('--provider-data',type=Path,required=True)
    parser.add_argument('--quantum-harbor',type=Path,required=True)
    parser.add_argument('--task-image-lock',type=Path,required=True)
    parser.add_argument('--reference-images',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output=args.output.resolve()
    args.output.mkdir(parents=True,exist_ok=False);args.output.chmod(0o700)
    data=args.output/'control';data.mkdir(mode=0o700)
    quantum=args.quantum_harbor.resolve();task_lock=json.loads(args.task_image_lock.read_text())
    if args.task_mode=='smoke':quantum,task_lock=smoke_task(quantum,args.output,task_lock)
    with sqlite3.connect(args.provider_data/'provider-settings.sqlite') as source,sqlite3.connect(data/'provider-settings.sqlite') as target:source.backup(target)
    (data/'provider-settings.sqlite').chmod(0o600)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    service=ControlService(ROOT,data,quantum,f'http://127.0.0.1:{port}')
    # Exact model/output settings are frozen before H0. Production settings remain untouched.
    for route in service.store.model_config['providers'].values():
        for model in route['models']:model['maxTokens']=4096
    service.store.model_config['providers']['openai-codex']['transport']='sse'
    mode=args.scenario;catalog={'revision':'unavailable','models':[]};refs=[];selected=None;profile_file=None
    if mode!='harness':
        route=service.store.model_config['providers']['deepseek-official']
        with service.providers.connection() as db:key=service.providers.credential(db,'deepseek-official',route)
        if not key:raise RuntimeError('Saved DeepSeek credential unavailable')
        profile={'apiKeyEnv':'REFERENCE_ACCEPTANCE_KEY','baseURL':route['baseURL'],'reasoningEffort':'off','maxTokens':4096,
            'retryPolicy':{'mode':'normal','maxRetries':0}}
        profile_file=args.output/'native-profile.json';write(profile_file,profile)
        secret=args.output/'native-credentials.json';secret.touch(mode=0o600);write(secret,{'version':1,'refs':{'REFERENCE_ACCEPTANCE_KEY':key},'records':{}})
        snapshot=args.output/'native-catalog.private.json'
        subprocess.run(['node',str(Path(__file__).with_name('native-profile.mjs')),str(profile_file),str(secret),str(snapshot)],cwd=ROOT,check=True)
        service.references.catalog.sync(json.loads(snapshot.read_text()));secret.unlink();snapshot.unlink()
        catalog=service.references.catalog.read();refs=[r['id'] for r in catalog['models']]
        selected=next(r['id'] for r in catalog['models'] if r['model']==('deepseek-v4-pro' if mode=='model' else 'deepseek-flash'))
    harnesses=['codex'] if mode=='harness' else ['claude-code','dsh-standard'] if mode=='joint' else []
    policy={**DEFAULT,'modelEnabled':mode!='harness','harnessEnabled':mode!='model','modelRefs':refs if mode=='joint' else [selected] if mode=='model' else [],'harnessRefs':harnesses,
        'catalogRevision':catalog['revision'],'limits':{a:{'maxTrials':2 if mode=='joint' else 1,'softTokenLimit':450000} for a in ['model','harness']}}
    solver={'provider':'openai-codex','model':'gpt-6-luna','reasoningEffort':'low'} if mode=='harness' else {'provider':'deepseek-official','model':'deepseek-flash','reasoningEffort':'off'}
    objective=('这是已授权的小规模工程验收。H0 已由后台真实执行；不要创建或优化插件，不追加主线实验。'
        '请先查看参考插件和兼容列表，在用户允许的参考模型与 Harness 中自主选择组合，提交最多两次联合参考：Claude Code 和 DeepSeek 标准模式各一次。'
        '根据成本优先选择模型，自主记录选择理由；不得修改允许集合。调用 reference_harness_submit 时必须带 modelRef。'
        '任务只使用当前公开任务，每次 repeats=1。提交后结束当前回复等待后台通知，避免循环查询。完成后读取实际轨迹、官方计分和用量证据，写简短验收分析；不能宣称科学提升。')
    if args.task_mode=='smoke':objective+='本活动只运行工程烟测任务副本，要求命令和 qsim 工具回环后结束、不提交科学答案；官方 no_submission / 0 是预期验收结果，不是科学能力测试。'
    config={'name':'Real reference acceptance: '+mode,'objective':objective,'solver':solver,
        'meta':solver if mode=='harness' else {'provider':'deepseek-official','model':'deepseek-flash','reasoningEffort':'off'},'tasks':[TASK],
        'maxRounds':5,'maxTrials':4,'concurrency':1,'wallTimeSeconds':1500,'trialTimeSeconds':450,
        'softTokenLimit':650000 if mode=='joint' else 500000,'reserveSeconds':0,'reserveTokens':0,'referencePolicy':policy,
        'taskImagePolicy':POLICY,'taskImageLocks':{TASK:task_lock}}
    defaults={**service.references.freeze(config),'metaComposition':freeze_meta(ROOT,data,config),'stopPolicy':'stop-review-v1'}
    expected_packages={('meta-'+axis+'-reference') for axis in ['model','harness'] if policy[axis+'Enabled']}
    assert set(defaults['metaComposition']['optionalToolContracts'])==expected_packages
    images=json.loads(args.reference_images.read_text())
    for harness in harnesses:defaults['referenceBindings']['harnesses'][harness].update(images[harness])
    campaign=service.store.create(config,'real-reference-'+mode,defaults=defaults)['id'];service.workspace(campaign)
    candidate=service.build_candidate(campaign,[],'真实模型验收 H0')
    write(args.output/'plan.json',{'scenario':mode,'campaignId':campaign,'config':config,'nativeProfile':str(profile_file) if profile_file else None,
        'costControl':'500000 shared soft threshold (650000 for Meta joint selection); 300000 reservation per request. Unknown calls retain their reservation. No whole-Trial retry. Codex uses explicit SSE transport frozen before H0.',
        'metaSelection':mode=='joint','task':TASK,'taskMode':args.task_mode,'scientificBenchmark':args.task_mode=='official'})
    server=uvicorn.Server(uvicorn.Config(make_app(service,supervise=False),log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    started=time.monotonic();last=None
    def tick():
        nonlocal last
        service.tick()
        status=service.status(campaign);write(args.output/'status.json',status)
        state=[(t['id'],t['state'],t.get('score'),t.get('outcome')) for t in service.store.runs(campaign)]
        if state!=last:print(json.dumps({'runs':state,'usage':status['usage']},ensure_ascii=False),flush=True);last=state
        if time.monotonic()-started>1450:raise TimeoutError('Acceptance wall time reached')
        return status
    try:
        while not server.started:time.sleep(.05)
        service.control(campaign,'start','start')
        while not service.store.list('trials',campaign) or any(t['state'] not in TERMINAL for t in service.store.list('trials',campaign)):tick();time.sleep(.5)
        baseline=service.store.list('trials',campaign)[0]
        if baseline['scoringStatus']!='completed':raise AssertionError('H0 official scoring missing: '+str(baseline.get('failure')))
        if mode=='joint':service.meta_driver=MetaDriver(service);service.meta_driver.start(campaign)
        else:
            axis='model' if mode=='model' else 'harness'
            service.references.call(campaign,'reference_'+axis+'_submit',{'candidateId':candidate['id'],
                **({'modelRef':selected} if axis=='model' else {'harnessRef':'codex'}),'tasks':[TASK],'repeats':1,
                'researchQuestion':'小规模真实模型验收：核对独立插件的轨迹、官方计分与共享预算。','expectedPolicyRevision':1,'idempotencyKey':'one-reference'})
        expected=2 if mode=='joint' else 1;selection_paused=False
        while True:
            status=tick();runs=service.store.list('reference_runs',campaign)
            if mode=='joint' and len(runs)==expected and not selection_paused and all(s['state']=='waiting' for s in service.store.list('meta_sessions',campaign)):
                # The paid acceptance scope ends Meta work after its actual autonomous
                # selection turn; pause/resume are recorded operator interventions.
                # This prevents evidence browsing from consuming the reference budget.
                service.control(campaign,'pause','selection-complete')
                for child in service.meta_driver.children.values():child.wait(timeout=20)
                service.meta_driver.tick(campaign);service.meta_driver=None;selection_paused=True
                service.control(campaign,'resume','execute-selected-references')
            if len(runs)==expected and all(t['state'] in TERMINAL for t in runs):break
            if status['state'] in ['finished','failed']:raise AssertionError('Activity ended before required coverage')
            if service.meta_driver and any(s['state']=='needs_attention' for s in service.store.list('meta_sessions',campaign)):raise AssertionError('Meta needs attention; inspect evidence')
            time.sleep(.5)
        # Stop further paid work once the requested coverage has finished; preserve the real Meta trace.
        if service.store.get('campaigns',campaign)['state'] in ['running','closing']:service.control(campaign,'pause','acceptance-covered')
        if service.meta_driver:
            for child in service.meta_driver.children.values():child.wait(timeout=20)
            service.meta_driver.tick(campaign)
        status=service.status(campaign);write(args.output/'status.json',status)
        proof=[]
        for row in service.store.runs(campaign):
            if row.get('output'):verify_manifest(Path(row['output']))
            requests=[u for u in service.store.list('usage',campaign) if u['leaseId']==row.get('leaseId')]
            confirmed=sum(u.get('confirmedTokens') or 0 for u in requests)
            assert confirmed==(row.get('usage') or {}).get('totalTokens',0),(row['id'],confirmed,row.get('usage'))
            assert row['scoringStatus']=='completed',row.get('failure')
            assert row['score'] is not None
            runtime_file=next(Path(row['output']).glob('harbor/*/phyexp/runtime-summary.json'))
            runtime=json.loads(runtime_file.read_text());assert runtime['toolCalls']>=2
            if args.task_mode=='smoke':assert row['outcome']=='no_submission' and row['score']==0
            proof.append({'id':row['id'],'reference':row.get('reference'),'state':row['state'],'score':row['score'],'outcome':row.get('outcome'),
                'scoringStatus':row['scoringStatus'],'confirmedTokens':confirmed,'requests':len(requests),'unknownRequests':sum(u['status']=='unknown' for u in requests),
                'model':runtime['model'],'toolCalls':runtime['toolCalls'],'output':row.get('output')})
        if mode=='joint':
            assert {r['reference']['harnessRef'] for r in runs}=={'claude-code','dsh-standard'}
            assert all(r['reference']['mode']=='joint-reference' for r in runs)
        assert len(service.store.list('trials',campaign))==1,'Reference changed primary Trial population'
        usage=service.store.list('usage',campaign)
        assert status['usage']['confirmedTokens']==sum(u.get('confirmedTokens') or 0 for u in usage)
        assert status['usage']['inflightReservedTokens']==0
        assert sum(t['score'] is not None for t in service.store.list('trials',campaign))==1
        write(args.output/'validation.json',{'passed':True,'scenario':mode,'campaignId':campaign,'runs':proof,'usage':status['usage'],'metaSubmitted':mode=='joint',
            'primaryTrials':1,'referenceTrials':expected,'evidenceFiles':len(service.store.list('evidence',campaign)),
            'taskMode':args.task_mode,'intervention':'Meta paused after autonomous selection turn; selected trials resumed without further paid Meta analysis. Activity paused after reference coverage. Not a scientific completion claim.' if selection_paused else 'Activity paused after reference coverage; not a scientific completion claim.'})
        print(json.dumps({'passed':True,'scenario':mode,'usage':status['usage']}),flush=True)
    except Exception as error:
        write(args.output/'validation.json',{'passed':False,'scenario':mode,'campaignId':campaign,'error':str(error),'usage':service.store.usage(campaign)})
        raise
    finally:
        if service.meta_driver:
            service.meta_driver.interrupt(campaign,'acceptance_cleanup')
            for child in service.meta_driver.children.values():
                if child.poll() is None:child.terminate();child.wait(timeout=20)
        for id,child in service.children.items():
            if child.poll() is None:service.stop_trial(service.store.run(id),'acceptance_cleanup');child.wait(timeout=40)
            row=service.store.run(id)
            if row['state'] in ['running','launching']:service._reconcile_trial(row)
        write(args.output/'status.json',service.status(campaign))
        server.should_exit=True;thread.join(10);service.pool.shutdown()

if __name__=='__main__':main()
