"""Real Harbor process/score contract using a scripted candidate and no model calls."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.execution.bundle.project import freeze_project
from src.control.execution_cache import prepare_runtime


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--quantum-harbor',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--exit-code',type=int,default=7)
    p.add_argument('--task',default='time_budgeted_hamlearn_10q')
    p.add_argument('--scenario',choices=['exit','timeout','cancel','supervisor-loss'],default='exit')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    cfg=json.loads(args.config.read_text());task=args.task
    assert task in cfg['tasks']
    image='node:24.13.0-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f'
    resources=json.loads((ROOT/'schemas/execution/process-resources.json').read_text())
    resources['brokerImage']=image
    recipe={'provider':'fixture','model':'scripted','timePolicy':'benchmark-time-v1',
        'providerConfig':{'adapter':'pi-ai','api':'openai-completions','baseURL':'https://unused.invalid/v1','auth':{'type':'api-key','env':'PHYEXP_PROCESS_FIXTURE_KEY'}},
        'processResources':resources}
    source=args.output/'source';source.mkdir()
    spec={'runContract':'harbor-process-v1','entrypoint':['main.py'], 'build':{'image':image,
        'argv':['/bin/sh','-c','chmod +x main.py'],'locks':['dependencies.lock']}}
    (source/'harness.json').write_text(json.dumps(spec));(source/'dependencies.lock').write_text('{"runtime":"task-python"}')
    (source/'main.py').write_text('''#!/usr/bin/env python3
import asyncio, json, os, sys, subprocess, signal, time
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
context=json.loads(Path(os.environ['PHYEXP_CONTEXT']).read_text())
# Probe only declared boundaries. Never enumerate or expose host credentials.
import urllib.request, urllib.error, socket
assert not any(Path(p).exists() for p in ('/var/run/docker.sock','/host','/verifier','/tests','/root/.codex/auth.json'))
assert 'PHYEXP_PROCESS_FIXTURE_KEY' not in os.environ
request=urllib.request.Request(context['modelChannel']['url']+'/v1/chat/completions',
    data=json.dumps({'model':'unauthorized-model','messages':[]}).encode(),
    headers={'Authorization':'Bearer '+context['modelChannel']['token'],'Content-Type':'application/json'})
try:urllib.request.urlopen(request,timeout=5)
except urllib.error.HTTPError as error:assert error.code==403,error.code
else:raise AssertionError('Different model was accepted')
try:socket.create_connection(('1.1.1.1',443),timeout=2)
except OSError:pass
else:raise AssertionError('Candidate has public network access')
assert set(context['resources']['task'])=={'main','qsim'}
async def main():
    async with streamablehttp_client(context['mcpServers'][0]['url']) as (r,w,_):
        async with ClientSession(r,w) as session:
            await session.initialize()
            result=await session.call_tool('list_devices',{})
            print(result.model_dump_json(),flush=True)
asyncio.run(main())
Path('/tmp/phyexp-output').mkdir(exist_ok=True)
Path('/tmp/phyexp-output/events.json').write_text('[]')
# PTY and background jobs run directly in the actual task workspace.
import pty
master,slave=pty.openpty();assert os.isatty(slave)
os.write(slave,b'candidate-pty');assert b'candidate-pty' in os.read(master,1024)
os.close(master);os.close(slave)
# Non-cooperative children share main's private PID namespace. Neither may survive.
for _ in range(2):subprocess.Popen([sys.executable,'-c',"import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(600)"])
Path('/tmp/phyexp-output/ready').write_text('ready')
if '''+repr(args.scenario)+'''!='exit':
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    time.sleep(600)
sys.exit('''+str(args.exit_code)+''')
''')
    with (args.output/'build.log').open('w') as log:
        frozen=freeze_project(ROOT,args.output/'objects',source,recipe,args.output/'cache',log,resources['build'])
    runtime=prepare_runtime(frozen['path'],args.output/'cache')
    task_root=args.quantum_harbor;task_lock=cfg['taskImageLocks'][task]
    if args.scenario=='timeout':
        # Explicit synthetic timing fixture, never a scientific comparison Trial.
        # Original Quantum-Harbor files/images are not modified.
        import shutil,re,hashlib
        from src.execution.host.single_run import task_image_sources
        task_root=args.output/'quantum-fixture';task_root.mkdir()
        for name in ('src','configs','docker','harbor_tasks','pyproject.toml','README.md','.dockerignore','uv.lock'):
            source=args.quantum_harbor/name;dest=task_root/name
            if source.is_dir():shutil.copytree(source,dest,ignore=shutil.ignore_patterns('__pycache__'))
            elif source.is_file():shutil.copyfile(source,dest)
        timing=task_root/'harbor_tasks'/task/'task.toml'
        text=timing.read_text();text,count=re.subn(r'(\[agent\][\s\S]*?timeout_sec\s*=\s*)[0-9.]+',r'\g<1>10',text,count=1)
        assert count==1;timing.write_text(text)
        task_lock={**task_lock,'taskSourcesDigest':hashlib.sha256(json.dumps(task_image_sources(task_root),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()}
    lock=args.output/'task-lock.json';lock.write_text(json.dumps(task_lock))
    os.environ['PHYEXP_PROCESS_FIXTURE_KEY']='fixture-only-no-model-call'
    trial=args.output/'trial'
    command=[sys.executable,str(runtime/'run.py'),'--bundle',frozen['path'],'--quantum-harbor',str(task_root),
             '--task',task,'--task-image-lock',str(lock),'--output',str(trial),'--deadline',str(time.time()+22000)]
    with (args.output/'supervisor.log').open('w') as log:
        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        if args.scenario in ('cancel','supervisor-loss'):
            expires=time.monotonic()+300
            while time.monotonic()<expires:
                paths=list(trial.glob('harbor/*/phyexp/runtime-summary.json'))
                identities=list(trial.glob('harbor/*/phyexp/isolation.json'))
                if paths and identities and list(trial.glob('harbor/*/phyexp/model-lease.json')):
                    main=json.loads(identities[0].read_text())['main']
                    ready=subprocess.run(['docker','exec',main,'test','-f','/tmp/phyexp-output/ready'],capture_output=True)
                    if ready.returncode==0:break
                if process.poll() is not None:raise RuntimeError('Supervisor exited before cancellation fixture')
                time.sleep(.2)
            else:raise TimeoutError('Candidate did not start')
            import signal
            process.send_signal(signal.SIGKILL if args.scenario=='supervisor-loss' else signal.SIGTERM)
        process.wait(timeout=600)
    if args.scenario=='supervisor-loss':
        from src.execution.host.single_run import cleanup
        cleanup(trial)
        assert_closed(trial)
        (args.output/'validation.json').write_text(json.dumps({'status':'passed','scenario':args.scenario,'realModelCalls':0,'scoreExpected':False}))
        return
    summary=json.loads((trial/'summary.json').read_text())
    if args.scenario=='cancel':
        assert summary['officialReward'] is None and summary['stopReason']=='user_stop',summary
    else:assert summary['officialReward']==0,summary
    if args.scenario=='exit':assert summary['execution']['exitCode']==args.exit_code,summary
    if args.scenario=='timeout':assert summary['execution']['status']=='timed_out',summary
    assert_closed(trial)
    if args.scenario in ('exit','timeout'):
        assert list(trial.glob('harbor/*/phyexp/candidate-output/events.json')),'Candidate diagnostics must retain their original names'
    result={'status':'passed','scenario':args.scenario,'task':task,'syntheticTiming':args.scenario=='timeout','bundleId':frozen['id'],'officialReward':summary['officialReward'],
            'execution':summary['execution'],'realModelCalls':0,'trial':str(trial)}
    (args.output/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
def assert_closed(trial):
    owner=json.loads((trial/'provenance.json').read_text()).get('launchId',trial.name)
    for command in (['network','ls','-q'],['ps','-aq']):
        owned=subprocess.check_output(['docker',*command,'--filter','label=phyexp.launch='+owner],text=True).strip()
        assert not owned,'Owned container/network remained after closeout'
    for file in trial.glob('harbor/*/phyexp/isolation.json'):
        isolation=json.loads(file.read_text())
        for role in ('main','qsim'):
            assert subprocess.run(['docker','inspect',isolation[role]],capture_output=True).returncode!=0,'Task container survived closeout'

if __name__=='__main__':main()
