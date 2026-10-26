"""Frozen native Meta + authenticated HTTP control, with a loopback fake provider.

Requires PHYEXP_META_TEST_IMAGE (immutable fixture image). No external model calls.
The provider never supplies an assistant reply after submitting the closeout tool.
"""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import uvicorn
from src.control.service import ControlService
from src.control.server import make_app
from src.control.meta import MetaDriver
from src.control.meta_native_composition import freeze
from src.control.stop_policy import META_POLICY
from src.control.collection import work

DECISION={'reason':'本次比较已经完成，无需额外实验。','summary':'未执行正式实验；完成了配置比较。\n效果与稳定性尚未验证。','idempotencyKey':'native-closeout'}
release=threading.Event()


class Provider(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.calls+=1
        if self.server.calls>1:
            # A missing follow-up response must not prevent durable closeout.
            release.wait(15)
            try:self.send_response(503);self.end_headers()
            except OSError:pass
            return
        finish=next(t['function'] for t in body['tools'] if t['function']['name']=='campaign_finish')
        assert set(finish['parameters']['properties'])==set(DECISION)
        delta={'role':'assistant','tool_calls':[{'index':0,'id':'finish','type':'function',
            'function':{'name':'campaign_finish','arguments':json.dumps(DECISION)}}]}
        events=[{'id':'fixture','object':'chat.completion.chunk','model':body['model'],
            'choices':[{'index':0,'delta':delta,'finish_reason':None}]},
            {'id':'fixture','object':'chat.completion.chunk','model':body['model'],
            'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]}]
        self.send_response(200);self.send_header('content-type','text/event-stream');self.end_headers()
        for event in events:self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()


def main():
    image=os.environ['PHYEXP_META_TEST_IMAGE']
    assert image.startswith('sha256:'),'Use an immutable fixture image'
    with tempfile.TemporaryDirectory(prefix='phyexp-closeout-') as temporary:
        data=Path(temporary);provider=ThreadingHTTPServer(('127.0.0.1',0),Provider);provider.calls=0
        threading.Thread(target=provider.serve_forever,daemon=True).start()
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        service=ControlService(ROOT,data,ROOT.parent/'Quantum-Harbor',f'http://127.0.0.1:{port}')
        driver=MetaDriver(service);service.meta_driver=driver
        model={'provider':'openai-codex','model':'gpt-6-astra','reasoningEffort':'medium'}
        cfg={'meta':model,'solver':model,'tasks':['time_budgeted_hamlearn_10q'],'concurrency':1,
            'wallTimeSeconds':120,'reserveSeconds':0,'stopPolicy':META_POLICY,'modelAccessPolicy':'control-only-v1',
            'objective':'比较配置并说明局限，不要求稳定性认证'}
        with patch('src.control.meta_native_composition.prepare_image',return_value=image):composition=freeze(ROOT,data,cfg)
        campaign=service.store.create(cfg,'fixture',defaults={'metaComposition':composition});c=campaign['id']
        campaign['config']['meta']['provider']='synthetic-meta'
        campaign['config']['modelRoutes']['meta']={'adapter':'pi-ai','api':'openai-completions',
            'baseURL':f'http://127.0.0.1:{provider.server_port}/v1','auth':{'type':'api-key','env':'PHYEXP_SYNTHETIC_CLOSEOUT_KEY'},
            'models':[{'id':'gpt-6-astra','maxTokens':1024,'contextWindow':32000,'defaultReasoningEffort':'medium','reasoningEfforts':{'medium':'medium'}}]}
        service.store.put('campaigns',campaign);service.store.control(c,'start','start')
        os.environ['PHYEXP_SYNTHETIC_CLOSEOUT_KEY']='synthetic-not-a-real-secret'
        server=uvicorn.Server(uvicorn.Config(make_app(service,supervise=False),log_level='error',lifespan='off'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        try:
            deadline=time.monotonic()+35
            while not server.started and time.monotonic()<deadline:time.sleep(.05)
            driver.start(c)
            while time.monotonic()<deadline:
                driver.tick(c)
                if service.store.status(c)['state']=='finished':break
                time.sleep(.05)
            result=service.store.status(c)
            assert result['state']=='finished',service.store.list('meta_sessions',c)
            assert result['finishAssessment']['reason']==DECISION['reason']
            assert result['finishAssessment']['summary']==DECISION['summary']
            assert not service.store.list('trials',c) and not service.store.list('reports',c)
            assert len(service.store.list('meta_sessions',c))==1
            assert provider.calls<=2,provider.calls
            replay=service.meta_api.call(c,'campaign_finish',DECISION)
            assert replay.get('state')=='closing',replay
            job=next(j for j in service.store.list('collection_jobs',c) if j['kind']=='report-summary')
            work(data,ROOT,job['id'],job['lockPath'])
            report=service.store.report_heads(c)[0]
            assert report['author']=='system' and report['closeoutSubmitted']
            report=service.store.get('reports',report['id'])
            assert DECISION['summary'] in Path(report['markdownPath']).read_text()
            print(json.dumps({'status':'passed','toolContract':composition['toolContract']['version'],
                'providerCalls':provider.calls,'postCloseoutReply':False,'externalModelCalls':0,'reportsRequired':False}))
        finally:
            release.set()
            for process in driver.children.values():
                if process.poll() is None:process.terminate();process.wait(timeout=10)
            server.should_exit=True;thread.join(5);provider.shutdown();provider.server_close()
            service.pool.shutdown();os.environ.pop('PHYEXP_SYNTHETIC_CLOSEOUT_KEY',None)


if __name__=='__main__':main()
