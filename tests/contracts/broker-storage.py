"""Actual bounded tmpfs ENOSPC; never fills a shared host filesystem or calls a model."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
args.output.mkdir(parents=True,exist_ok=False)
image=json.loads((ROOT/'schemas/execution/process-resources.json').read_text())['brokerImage']
script='''import fs from 'node:fs';import assert from 'node:assert/strict';import {serve} from '/broker/broker.mjs';
fs.writeFileSync('/audit/fill',Buffer.alloc(1024*1024));let calls=0;
const proxy=await serve({binding:{model:{model:'fixed'},protocol:'responses',baseURL:'https://unused.invalid',headers:{}},token:'fixture',deadline:Date.now()+10000,requestBytes:4096,audit:'/audit/audit.jsonl',fetchImpl:async()=>{calls++;return new Response('unused');}});
try{const r=await fetch(proxy.url+'/responses',{method:'POST',headers:{authorization:'Bearer fixture'},body:'{"model":"fixed"}'});const body=await r.text();assert.equal(r.status,507);assert.match(body,/ENOSPC/);assert.equal(calls,0);console.log(JSON.stringify({status:'passed',httpStatus:r.status,cause:'actual tmpfs ENOSPC',realModelCalls:0}));}finally{await proxy.close();}
'''
result=subprocess.run(['docker','run','--rm','--network','none','--cap-drop=ALL','--security-opt=no-new-privileges','--memory','256m','--pids-limit','64',
 '--tmpfs','/audit:rw,size=1048576,mode=1777','-v',str(ROOT/'src/execution/process')+':/broker:ro','--entrypoint','node',image,'--input-type=module','-e',script],capture_output=True,text=True,timeout=60)
(args.output/'stdout.log').write_text(result.stdout);(args.output/'stderr.log').write_text(result.stderr);result.check_returncode()
validation=json.loads(result.stdout);(args.output/'validation.json').write_text(json.dumps(validation,indent=2));print(result.stdout)
