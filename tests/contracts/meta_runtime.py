"""Full frozen Meta host + authenticated controller + native reviewer, using only loopback synthetic SSE."""
import hashlib,json,os,socket,sys,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.control.service import ControlService
from src.control.server import make_app
from src.control.meta import MetaDriver
from src.control.meta_composition import freeze
import uvicorn
PLANNING='--resource-planning' in sys.argv
NATIVE='--native' in sys.argv
RECOVERY='--recover' in sys.argv
FINAL_FIRST='--final-first' in sys.argv
CLOSEOUT_DENIAL='--closeout-budget-denial' in sys.argv
if CLOSEOUT_DENIAL:assert NATIVE and not (RECOVERY or FINAL_FIRST or PLANNING)
PLAN={'parallelism':1,'defaultTrialTimeSeconds':600,'closeoutReserveSeconds':0,'closeoutReserveTokens':0}

class Provider(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));messages=body['messages'];tools={t['function']['name'] for t in body.get('tools',[])}
        child='structured_output' in tools
        self.server.calls.append({'child':child,'tools':sorted(tools)})
        if RECOVERY and len(self.server.calls)==1:
            self.send_response(503);self.send_header('content-type','application/json');self.end_headers()
            self.wfile.write(b'{"error":{"message":"fixture temporary overload","code":"overloaded"}}');return
        count=sum(m['role']=='tool' for m in messages)
        request=self.server.request
        if NATIVE:
            analysis={'brief':'Native synthetic report','researchRefs':[],'summary':'Native synthetic report','observations':['Fixture only'],'hypotheses':[],'limitations':['No real model'],'decision':'Closeout','evidenceRefs':['evidence-fixture']}
            if child:
                assert 'campaign_finish' not in tools and 'subagent' not in tools
                name,args=('evidence_read',{'id':'evidence-fixture'}) if count==0 else ('structured_output',{'verdict':'approve','reason':'Independent evidence read','evidenceRefs':['evidence-fixture'],'missingEvidence':[],'nextDirections':[]})
            elif count==0:name,args='campaign_finish',{**request,'idempotencyKey':'finish-native'}
            elif FINAL_FIRST and count==3 and not getattr(self.server,'round_notice_seen',False):
                if not getattr(self.server,'final_turn_ended',False):
                    self.server.final_turn_ended=True;name,args=None,None
                else:
                    latest=next(m['content'] for m in reversed(messages) if m['role']=='user')
                    assert self.server.batch in str(latest) and '尚缺 1 份每轮报告' in str(latest),latest
                    self.server.round_notice_seen=True;name,args='report_get_facts',{'batchId':self.server.batch}
            elif count in [1,3]:name,args='report_get_facts',({'batchId':self.server.batch} if count==(3 if FINAL_FIRST else 1) else {})
            elif count in [2,4]:
                import re
                content=next(m['content'] for m in reversed(messages) if m['role']=='tool')
                if isinstance(content,list):content='\n'.join(x.get('text','') for x in content)
                facts_id=re.search(r'"factsId"\s*:\s*"([0-9a-f]{64})"',content).group(1)
                name,args='report_save',{'factsId':facts_id,'analysis':analysis,'expectedReportRevision':0,'idempotencyKey':'report-'+str(count)}
            else:name,args=None,None
        elif child:
            assert 'workspace_write' not in tools and 'campaign_finish' not in tools
            name,args=('evidence_read',{'input':json.dumps({'id':'evidence-fixture'})}) if count==0 else ('structured_output',{'verdict':'approve','reason':'Synthetic evidence independently read','evidenceRefs':['evidence-fixture'],'missingEvidence':[],'nextDirections':[]})
        elif PLANNING and count==0:
            name,args='campaign_plan_update',{'input':json.dumps({'changes':{**PLAN,'defaultTrialTimeSeconds':500},'reason':'Native Meta adjusts future allocation','expectedPlanRevision':1,'idempotencyKey':'native-plan'})}
        elif count==(1 if PLANNING else 0):name,args='campaign_finish',{'input':json.dumps(request)}
        elif count in ([2,3] if PLANNING else [1,2]):
            analysis={'summary':'Synthetic report','observations':['Fixture only'],'hypotheses':[],'limitations':['No real model or science result'],'decision':'Synthetic closeout','evidenceRefs':['evidence-fixture']}
            if count==(2 if PLANNING else 1):analysis['batchId']=self.server.batch
            name,args='report_save',{'input':json.dumps(analysis)}
        else:name,args=None,None
        delta={'role':'assistant','tool_calls':[{'index':0,'id':'fixture-'+str(len(self.server.calls)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]} if name else {'role':'assistant','content':'Synthetic complete'}
        events=[{'id':'fixture','object':'chat.completion.chunk','model':body['model'],'choices':[{'index':0,'delta':delta,'finish_reason':None}]},{'id':'fixture','object':'chat.completion.chunk','model':body['model'],'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls' if name else 'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}]
        self.send_response(200);self.send_header('content-type','text/event-stream');self.end_headers()
        for e in events:self.wfile.write(('data: '+json.dumps(e)+'\n\n').encode());self.wfile.flush()

with tempfile.TemporaryDirectory(prefix='phyexp-meta-runtime-') as temporary:
    data=Path(temporary);provider=ThreadingHTTPServer(('127.0.0.1',0),Provider);provider.calls=[]
    threading.Thread(target=provider.serve_forever,daemon=True).start()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    service=ControlService(ROOT,data,ROOT.parent/'Quantum-Harbor',f'http://127.0.0.1:{port}');driver=MetaDriver(service);service.meta_driver=driver
    model={'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'}
    cfg={'meta':model,'solver':{**model,'model':'gpt-6-sol'},'tasks':['time_budgeted_hamlearn_10q'],'concurrency':1,'wallTimeSeconds':120,'reserveSeconds':5,
         'metaCompositionConfig':json.loads((ROOT/'packages/meta-harness/composition.json').read_text())}
    if NATIVE:cfg.pop('metaCompositionConfig')
    # Seven responses (including two reviewer responses) commit both reports.
    # The eighth request cannot reserve 300,000 tokens for the final model reply.
    if CLOSEOUT_DENIAL:cfg.update(softTokenLimit=300072,reserveTokens=0)
    if PLANNING:cfg.update(resourcePolicy='meta-resource-planning-v1',wallTimeSeconds=1200)
    composition=freeze(ROOT,data,cfg);campaign=service.store.create(cfg,'fixture',defaults={'stopPolicy':'stop-review-v1','metaComposition':composition})
    c=campaign['id'];service.store.control(c,'start','start');candidate=service.store.candidate(c,{'id':'fixture','path':str(data/'nonexistent-bundle'),'plugins':[]},'Synthetic H0',check={'status':'passed'})
    if PLANNING:service.store.update_plan(c,PLAN,'Initial fixture plan','initial-plan',0,source='operator')
    batch=service.store.submit(c,candidate['id'],cfg['tasks'],1,'fixture');trial=service.store.list('trials',c)[0];service.store.trial_update(trial['id'],state='finished',score=1,startedAt=time.time(),finishedAt=time.time())
    evidence=data/'evidence.json';evidence.write_text('{"fixture":true}')
    service.store.put('evidence',{'id':'evidence-fixture','campaignId':c,'trialId':trial['id'],'kind':'runtime','path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest(),'size':evidence.stat().st_size,'bytes':evidence.stat().st_size,'source':{'archive':'fixture.json'},'policy':'public-development-full-v2' if NATIVE else 'public-development-v1'})
    campaign=service.store.get('campaigns',c);campaign['config']['meta']['provider']='synthetic-meta';campaign['config']['modelRoutes']['meta']={'adapter':'pi-ai','api':'openai-completions','baseURL':f'http://127.0.0.1:{provider.server_port}/v1','auth':{'type':'api-key','env':'PHYEXP_SYNTHETIC_META_KEY'},'models':[{'id':'gpt-6-astra','maxTokens':1024,'contextWindow':32000,'defaultReasoningEffort':'medium','reasoningEfforts':{'medium':'medium'}}]};service.store.put('campaigns',campaign)
    os.environ['PHYEXP_SYNTHETIC_META_KEY']='synthetic-not-a-real-secret'
    provider.request={'condition':'exhausted','candidateId':candidate['id'],'reason':'Synthetic exhaustion fixture','evidenceRefs':['evidence-fixture'],'attempts':[{'direction':'Fixture direction','finding':'Fixture result','evidenceRefs':['evidence-fixture']}],'remainingDirections':[],'unresolved':[]};provider.batch=batch['id']
    server=uvicorn.Server(uvicorn.Config(make_app(service,supervise=False),host='127.0.0.1',port=port,log_level='error'));thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        deadline=time.monotonic()+40
        while not server.started and time.monotonic()<deadline:time.sleep(.05)
        driver.start(c);process=next(iter(driver.children.values()))
        while time.monotonic()<deadline:
            if RECOVERY:
                driver.tick(c)
                sessions=service.store.list('meta_sessions',c)
                if service.store.status(c)['state']=='finished':break
                if sessions[-1]['state']=='needs_attention':raise AssertionError(sessions[-1])
            elif process.poll() is not None:break
            time.sleep(.1)
        if not RECOVERY and process.poll() is None:raise AssertionError('Frozen worker failed to close out')
        session=service.store.list('meta_sessions',c)[-1];summary=json.loads((Path(session['output'])/'summary.json').read_text())
        if CLOSEOUT_DENIAL:
            assert summary['status']=='error' and summary['failure']['code']=='budget_admission_denied',summary
        else:assert summary['status']=='completed',summary
        driver.tick(c)
        review=service.store.list('stop_reviews',c)[0];assert review['state']=='consumed',review
        assert review['usage']['confirmedTokens']==24,review['usage']
        expected_tokens=84 if CLOSEOUT_DENIAL else (108 if FINAL_FIRST else 96) if NATIVE else 84 if PLANNING else 72
        assert service.store.usage(c)['confirmedTokens']==expected_tokens,service.store.usage(c)
        if PLANNING:
            plan=service.store.get('campaigns',c)['resourcePlan']
            assert plan['revision']==2 and plan['source']=='meta' and plan['defaultTrialTimeSeconds']==500,plan
            assert service.store.get('batches',batch['id'])['testSettings']['trialTimeSeconds']==600
        assert service.store.status(c)['state']=='finished'
        if CLOSEOUT_DENIAL:
            assert service.store.get('meta_sessions',session['id'])['state']=='needs_attention'
            reports=service.store.list('reports',c)
            assert len(reports)==2 and all(r['status']=='analysis' and r['analysisRevision']==1 for r in reports),reports
            assert len(provider.calls)==7,provider.calls
        assert len(service.store.get('meta_sessions',session['id'])['agents'])==2
        if RECOVERY:
            sessions=service.store.list('meta_sessions',c);assert len(sessions)==2,[{k:s.get(k) for k in ['id','state','summary']} for s in sessions]
            assert sessions[0]['nativeSessionId']==sessions[1]['nativeSessionId']
            assert summary['resumed'] and sessions[1]['recoveryAttempt']==1
            assert not service.store.get('campaigns',c)['stopReason']=='meta_session_failed'
        print(json.dumps({'status':'passed','native':NATIVE,'resourcePlanning':PLANNING,'closeoutBudgetDenial':CLOSEOUT_DENIAL,'providerCalls':len(provider.calls),'reviewCalls':sum(x['child'] for x in provider.calls),'sharedTokens':expected_tokens,'reviewTokensIncluded':24,'frozenComposition':composition['id'],'externalModelCalls':0}))
    finally:
        for process in driver.children.values():
            if process.poll() is None:process.terminate();process.wait(timeout=10)
        server.should_exit=True;thread.join(5);provider.shutdown();service.pool.shutdown();os.environ.pop('PHYEXP_SYNTHETIC_META_KEY',None)
