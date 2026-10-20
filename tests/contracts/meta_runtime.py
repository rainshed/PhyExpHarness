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
PLAN={'parallelism':1,'defaultTrialTimeSeconds':600,'closeoutReserveSeconds':0,'closeoutReserveTokens':0}

class Provider(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));messages=body['messages'];tools={t['function']['name'] for t in body.get('tools',[])}
        child='structured_output' in tools
        self.server.calls.append({'child':child,'tools':sorted(tools)})
        count=sum(m['role']=='tool' for m in messages)
        request=self.server.request
        if child:
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
    cfg={'meta':model,'solver':{**model,'model':'gpt-6-sol'},'tasks':['time_budgeted_hamlearn_10q'],'concurrency':1,'wallTimeSeconds':120,'reserveSeconds':5}
    if PLANNING:cfg.update(resourcePolicy='meta-resource-planning-v1',wallTimeSeconds=1200)
    composition=freeze(ROOT,data,cfg);campaign=service.store.create(cfg,'fixture',defaults={'stopPolicy':'stop-review-v1','metaComposition':composition})
    c=campaign['id'];service.store.control(c,'start','start');candidate=service.store.candidate(c,{'id':'fixture','path':str(data/'nonexistent-bundle'),'plugins':[]},'Synthetic H0',check={'status':'passed'})
    if PLANNING:service.store.update_plan(c,PLAN,'Initial fixture plan','initial-plan',0,source='operator')
    batch=service.store.submit(c,candidate['id'],cfg['tasks'],1,'fixture');trial=service.store.list('trials',c)[0];service.store.trial_update(trial['id'],state='finished',score=1,startedAt=time.time(),finishedAt=time.time())
    evidence=data/'evidence.json';evidence.write_text('{"fixture":true}')
    service.store.put('evidence',{'id':'evidence-fixture','campaignId':c,'trialId':trial['id'],'kind':'runtime','path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest(),'size':evidence.stat().st_size})
    campaign=service.store.get('campaigns',c);campaign['config']['meta']['provider']='synthetic-meta';campaign['config']['modelRoutes']['meta']={'adapter':'pi-ai','api':'openai-completions','baseURL':f'http://127.0.0.1:{provider.server_port}/v1','auth':{'type':'api-key','env':'PHYEXP_SYNTHETIC_META_KEY'},'models':[{'id':'gpt-6-astra','maxTokens':1024,'contextWindow':32000,'defaultReasoningEffort':'medium','reasoningEfforts':{'medium':'medium'}}]};service.store.put('campaigns',campaign)
    os.environ['PHYEXP_SYNTHETIC_META_KEY']='synthetic-not-a-real-secret'
    provider.request={'condition':'exhausted','candidateId':candidate['id'],'reason':'Synthetic exhaustion fixture','evidenceRefs':['evidence-fixture'],'attempts':[{'direction':'Fixture direction','finding':'Fixture result','evidenceRefs':['evidence-fixture']}],'remainingDirections':[],'unresolved':[]};provider.batch=batch['id']
    server=uvicorn.Server(uvicorn.Config(make_app(service,supervise=False),host='127.0.0.1',port=port,log_level='error'));thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        deadline=time.monotonic()+40
        while not server.started and time.monotonic()<deadline:time.sleep(.05)
        driver.start(c);process=next(iter(driver.children.values()))
        while process.poll() is None and time.monotonic()<deadline:time.sleep(.1)
        if process.poll() is None:raise AssertionError('Frozen worker failed to close out')
        session=service.store.list('meta_sessions',c)[0];summary=json.loads((Path(session['output'])/'summary.json').read_text())
        assert summary['status']=='completed',summary
        driver.tick(c)
        review=service.store.list('stop_reviews',c)[0];assert review['state']=='consumed',review
        assert review['usage']['confirmedTokens']==24,review['usage']
        expected_tokens=84 if PLANNING else 72
        assert service.store.usage(c)['confirmedTokens']==expected_tokens,service.store.usage(c)
        if PLANNING:
            plan=service.store.get('campaigns',c)['resourcePlan']
            assert plan['revision']==2 and plan['source']=='meta' and plan['defaultTrialTimeSeconds']==500,plan
            assert service.store.get('batches',batch['id'])['testSettings']['trialTimeSeconds']==600
        assert service.store.status(c)['state']=='finished'
        assert len(service.store.get('meta_sessions',session['id'])['agents'])==2
        print(json.dumps({'status':'passed','resourcePlanning':PLANNING,'providerCalls':len(provider.calls),'reviewCalls':sum(x['child'] for x in provider.calls),'sharedTokens':expected_tokens,'reviewTokensIncluded':24,'frozenComposition':composition['id'],'externalModelCalls':0}))
    finally:
        for process in driver.children.values():
            if process.poll() is None:process.terminate();process.wait(timeout=10)
        server.should_exit=True;thread.join(5);provider.shutdown();service.pool.shutdown();os.environ.pop('PHYEXP_SYNTHETIC_META_KEY',None)
