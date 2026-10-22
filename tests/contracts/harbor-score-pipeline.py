"""Real Harbor/Docker/official verifier -> controller DB; scripted local provider, no paid model.

Requires the unchanged Quantum-Harbor checkout and a prepared hamlearn image lock.
All writes, trials, accounting and API state belong to --output, never the user's campaigns.
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import uvicorn
from src.control.service import ControlService
from src.control.server import make_app
from src.control.execution_cache import prepare_runtime
from src.control.runner_images import prepare_runner_image
from src.control.task_images import POLICY
from src.execution.bundle.freeze import freeze
from src.execution.adapters.quantum_harbor.results import verify_manifest

TASK = 'time_budgeted_hamlearn_10q'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quantum-harbor', required=True, type=Path)
    parser.add_argument('--task-image-lock', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--native-meta',action='store_true',help='Continue with native Meta investigation, plugin check/freeze and a second official Trial')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    requests = []
    provider_errors = []
    from meta_investigation_fixture import Investigation
    investigation=Investigation()

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert self.headers['Authorization'] == 'Bearer fixture-key'
                assert body['model'] == 'fixture-model'
                names=[t['function']['name'] for t in body['tools']]
                is_meta='candidate_check' in names
                step=sum(m['role']=='tool' for m in body['messages'])
                if not is_meta:requests.append({'step':step,'tools':names})
                messages = json.dumps(body['messages'])
                if is_meta:name,arguments=investigation.reply(body)
                elif step == 0:
                    name, arguments = 'bash', {'command': ''}
                elif step == 1:
                    assert 'Only a nonempty command' in messages
                    name, arguments = 'bash', {'command': "printf 'fixture bridge recovered\\n'"}
                elif step == 2:
                    assert 'fixture bridge recovered' in messages
                    name = next(n for n in requests[-1]['tools'] if n.endswith('__list_devices'))
                    arguments = {}
                else:
                    assert step == 3
                    assert 'hamlearn_10q' in messages
                    name = None
                delta = ({'role':'assistant', 'tool_calls':[{'index':0,'id':f'fixture-{step}','type':'function',
                         'function':{'name':name,'arguments':json.dumps(arguments)}}]} if name else
                         {'role':'assistant','content':'Engineering fixture complete; intentionally no scientific submission.'})
                chunks = [
                    {'id':'fixture','object':'chat.completion.chunk','model':'fixture-model',
                     'choices':[{'index':0,'delta':delta,'finish_reason':None}]},
                    {'id':'fixture','object':'chat.completion.chunk','model':'fixture-model',
                     'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls' if name else 'stop'}],
                     'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}},
                ]
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                self.wfile.write(''.join('data: '+json.dumps(x)+'\n\n' for x in chunks).encode())
            except Exception as error:
                provider_errors.append(repr(error))
                self.send_error(500, 'Fixture assertion failed')

    provider = ThreadingHTTPServer(('127.0.0.1',0), Provider)
    provider_thread = threading.Thread(target=provider.serve_forever,daemon=True);provider_thread.start()
    listener = socket.socket();listener.bind(('127.0.0.1',0));port = listener.getsockname()[1]
    route = {'adapter':'pi-ai','api':'openai-completions','baseURL':f'http://127.0.0.1:{provider.server_port}/v1',
             'auth':{'type':'api-key','env':'PHYEXP_PIPELINE_FIXTURE_KEY'},
             'models':[{'id':'fixture-model','reasoningEfforts':False,'maxTokens':1024,'contextWindow':16000}]}
    os.environ['PHYEXP_PIPELINE_FIXTURE_KEY'] = 'fixture-key'
    service = ControlService(ROOT,args.output/'control',args.quantum_harbor,f'http://127.0.0.1:{port}')
    service.store.model_config = {'schemaVersion':1,'providers':{'pipeline-fixture':route}}
    config = {'solver':{'provider':'pipeline-fixture','model':'fixture-model'},
              'meta':{'provider':'pipeline-fixture','model':'fixture-model'},'tasks':[TASK],
              'maxRounds':3 if args.native_meta else 1,'maxTrials':3 if args.native_meta else 1,'concurrency':1,'wallTimeSeconds':1800,'trialTimeSeconds':900,
              'softTokenLimit':None,'reserveSeconds':0,'reserveTokens':0,
              'taskImagePolicy':POLICY,'taskImageLocks':{TASK:json.loads(args.task_image_lock.read_text())}}
    defaults=None
    if args.native_meta:
        from src.control.meta_composition import freeze as freeze_meta
        defaults={'stopPolicy':'stop-review-v1','metaComposition':freeze_meta(ROOT,service.data,config)}
    campaign = service.store.create(config,'pipeline-fixture',defaults=defaults)['id']
    service.workspace(campaign)
    recipe = json.loads((ROOT/'recipes/h0-sol.json').read_text())
    recipe.update(config['solver'],providerConfig=route,agentTimeoutSec=120,maxTokens=1024)
    recipe.pop('reasoningEffort',None)
    bundle = freeze(ROOT,args.output/'objects',recipe)
    assert 'id' not in json.loads((Path(bundle['path'])/'recipe.json').read_text())
    runtime = prepare_runtime(bundle['path'],service.data/'cache')
    with (args.output/'runner.log').open('w') as log:
        prepare_runner_image(runtime,service.data/'runner-locks',log)
    candidate = service.build_candidate(campaign,[],'Engineering baseline') if args.native_meta else service.store.candidate(campaign,bundle,'Engineering pipeline fixture',check={'status':'passed'})
    service.store.control(campaign,'start','start')
    service.store.submit(campaign,candidate['id'],[TASK],1,'one')
    server = uvicorn.Server(uvicorn.Config(make_app(service,supervise=False),log_level='error',lifespan='off'))
    api_thread = threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);api_thread.start()
    trial = None
    try:
        start = time.monotonic()
        while not server.started:
            if time.monotonic()-start > 10:raise RuntimeError('Fixture API did not start')
            time.sleep(.05)
        trial = service._launch(service.store.claim(campaign))
        while time.monotonic()-start < 600:
            service._reconcile_trial(service.store.get('trials',trial['id']))
            row = service.store.get('trials',trial['id'])
            if row['state'] not in ['launching','running']:break
            time.sleep(.5)
        else:raise TimeoutError('Pipeline did not finish')
        (args.output/'trial.json').write_text(json.dumps(row,indent=2))
        assert not provider_errors, provider_errors
        assert len(requests) == 4, requests
        assert row['state'] == 'finished', row.get('summary')
        assert row['score'] == 0 and row['outcome'] == 'no_submission', row.get('summary')
        assert row['scoringStatus'] == 'completed' and row['failure'] is None
        assert row['usage']['totalTokens'] == 48
        output = Path(row['output'])
        verify_manifest(output)
        harbor = json.loads(next(output.glob('harbor/*/result.json')).read_text())
        assert harbor['exception_info'] is None and harbor['verifier_result']['rewards']['reward'] == 0
        bridge = [json.loads(line) for line in next(output.glob('harbor/*/phyexp/container-exec.jsonl')).read_text().splitlines()]
        assert any(e.get('phase') == 'rejected' for e in bridge)
        assert any(e.get('phase') == 'end' and 'fixture bridge recovered' in e.get('stdout','') for e in bridge)
        req = urllib.request.Request(service.base_url+'/campaigns/'+campaign,
                                     headers={'Authorization':'Bearer '+service.user_token})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req) as response:
            shown = json.load(response)
        assert shown['taskEvaluation']['total']['officialScored'] == 1
        assert shown['trials'][0]['taskAssessment']['category'] == 'failed'
        assert shown['usage']['confirmedTokens'] == 48, shown['usage']
        proof = {'status':'passed','campaignId':campaign,'trialId':row['id'],'officialReward':row['score'],
                 'taskOutcome':row['outcome'],'scriptedProviderRequests':len(requests),'realModelCalls':0,
                 'pipeline':['controller launch','frozen v2 worker','isolated DeepSeek','empty bash rejection',
                             'successful bash','qsim MCP','official Harbor verifier','archive','DB','authenticated API'],
                 'archive':str(output),'requests':requests}
        if args.native_meta:
            from src.control.meta import MetaDriver
            service.meta_driver=MetaDriver(service);service.meta_driver.start(campaign)
            deadline=time.monotonic()+300
            while investigation.stage<9 and time.monotonic()<deadline:
                service.tick();time.sleep(.2)
                assert not provider_errors,provider_errors
                latest=service.store.list('meta_sessions',campaign)[-1]
                assert latest['state']!='needs_attention',latest
            assert investigation.stage==9,(investigation.stage,service.status(campaign))
            service.control(campaign,'pause','fixture-end')
            for child in service.meta_driver.children.values():child.wait(timeout=15)
            service.meta_driver.tick(campaign)
            trials=service.store.list('trials',campaign)
            assert len(trials)==2 and all(t['score']==0 and t['scoringStatus']=='completed' for t in trials),trials
            assert len(requests)==8,requests
            evidence=service.store.list('evidence',campaign)
            assert all(e['policy']=='public-development-full-v2' for e in evidence)
            analysis=service.data/'campaigns'/campaign/'meta-work/analysis/investigation.json'
            assert json.loads(analysis.read_text())
            proof.update(metaProviderCalls=investigation.calls,secondTrialId=trials[1]['id'],candidateId=investigation.candidate,analysis=str(analysis),evidenceFiles=len(evidence),scriptedProviderRequests=len(requests),metaPipeline=['complete score and trajectory paths','native Python analysis','native plugin write','candidate check','freeze','batch submit','official verifier','DB','results_compare'])
        (args.output/'validation.json').write_text(json.dumps(proof,indent=2))
        print(json.dumps(proof))
    finally:
        if service.meta_driver:
            for child in service.meta_driver.children.values():
                if child.poll() is None:child.terminate();child.wait(timeout=15)
        if trial:
            child = service.children.get(trial['id'])
            if child and child.poll() is None:
                service.stop_trial(service.store.get('trials',trial['id']),'user_stop')
                child.wait(timeout=30)
        server.should_exit=True;api_thread.join(10)
        provider.shutdown();provider.server_close();service.pool.shutdown()


if __name__ == '__main__':
    main()
