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
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    cfg=json.loads(args.config.read_text());task='time_budgeted_hamlearn_10q'
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
import asyncio, json, os, sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
context=json.loads(Path(os.environ['PHYEXP_CONTEXT']).read_text())
async def main():
    async with streamablehttp_client(context['mcpServers'][0]['url']) as (r,w,_):
        async with ClientSession(r,w) as session:
            await session.initialize()
            result=await session.call_tool('list_devices',{})
            print(result.model_dump_json(),flush=True)
asyncio.run(main())
Path('/tmp/phyexp-output').mkdir(exist_ok=True)
Path('/tmp/phyexp-output/events.json').write_text('[]')
sys.exit('''+str(args.exit_code)+''')
''')
    with (args.output/'build.log').open('w') as log:
        frozen=freeze_project(ROOT,args.output/'objects',source,recipe,args.output/'cache',log,resources['build'])
    runtime=prepare_runtime(frozen['path'],args.output/'cache')
    lock=args.output/'task-lock.json';lock.write_text(json.dumps(cfg['taskImageLocks'][task]))
    os.environ['PHYEXP_PROCESS_FIXTURE_KEY']='fixture-only-no-model-call'
    trial=args.output/'trial'
    command=[sys.executable,str(runtime/'run.py'),'--bundle',frozen['path'],'--quantum-harbor',str(args.quantum_harbor),
             '--task',task,'--task-image-lock',str(lock),'--output',str(trial),'--deadline',str(time.time()+22000)]
    with (args.output/'supervisor.log').open('w') as log:
        completed=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=600)
    summary=json.loads((trial/'summary.json').read_text())
    assert summary['officialReward']==0,summary
    assert summary['scoringStatus']=='completed',summary
    assert summary['execution']['exitCode']==args.exit_code,summary
    result={'status':'passed','bundleId':frozen['id'],'officialReward':summary['officialReward'],
            'execution':summary['execution'],'realModelCalls':0,'trial':str(trial)}
    (args.output/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
