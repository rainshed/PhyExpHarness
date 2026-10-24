import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {DshSession} from '../../src/execution/runner/dsh_session.mjs';
import {MetaGateway} from '../../src/control/meta_gateway.mjs';
import {ModelGateway,hostFailureDiagnostics} from '../../src/execution/host/model_gateway.mjs';

test('RPC disk failure remains primary through model cancellation, exit and repeated final saves',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-log-failure-'));
 t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const model={provider:'fixture',model:'fixture'},audit=path.join(dir,'gateway-audit.jsonl');
 let started,settled;const start=new Promise(r=>started=r),end=new Promise(r=>settled=r);
 const gateway=new MetaGateway({mainSessionId:'main',model,deadline:Date.now()+5000,audit,
  adapter:{async *stream({signal}){started();await new Promise((_,reject)=>{signal.addEventListener('abort',()=>reject(new Error('Fixture cancelled')),{once:true});});}},
  settle:async()=>settled()});
 const rpc=path.join(dir,'rpc.jsonl'),append=fs.appendFileSync;
 t.mock.method(fs,'appendFileSync',(file,data,...rest)=>{
  if(file===rpc&&String(data).includes('fixture-disk-failure'))throw Object.assign(new Error('No space left on device'),{code:'ENOSPC'});
  return append(file,data,...rest);
 });
 const script=`const rl=require('node:readline').createInterface({input:process.stdin});
 const send=x=>process.stdout.write(JSON.stringify(x)+'\\n');
 rl.on('line',line=>{const r=JSON.parse(line);
  if(r.id)send({id:r.id,result:{}});
  if(r.method==='session/prompt')send({method:'phyexp/request',params:{id:'model-1',operation:'model',payload:{sessionId:'main',provider:'fixture',model:'fixture',messages:[]}}});
  if(r.method==='fixture-disk-failure')send({method:'session.event',params:{sessionId:'main',event:{type:'fixture-disk-failure'}}});
 });`;
 const session=new DshSession({executable:process.execPath,args:['-e',script],workspace:dir,home:dir,rpcLog:rpc,stderrLog:path.join(dir,'stderr.log'),
  async *handleRequest(op,payload,signal){yield* gateway.stream(payload,signal);}});
 t.after(()=>session.dispose());
 const prompt=session.prompt('main','start',5000);const rejected=assert.rejects(prompt,e=>e.hostFailure?.code==='storage_capacity');
 await start;session.proc.stdin.write(JSON.stringify({method:'fixture-disk-failure'})+'\n');
 await rejected;await session.exited;await end;
 const summary={status:'error',hostFailure:session.failure};
 for(let i=0;i<2;i++){
  Object.assign(summary,gateway.persistFinal(summary));
  assert.equal(summary.failure.code,'storage_capacity');assert.equal(summary.failure.stage,'logging');
  assert.equal(summary.failure.observed.errorCode,'ENOSPC');
  assert.deepEqual(summary.failure.secondaryCodes,['request_cancelled']);
  assert.equal(summary.requestRecovery.failures[0].code,'request_cancelled');
  const saved=JSON.parse(fs.readFileSync(path.join(dir,'failure.json')));
  assert.equal(saved.failure.code,'storage_capacity');
 }
});

test('failure before the first model channel is still saved with the original host cause',t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-log-bootstrap-'));
 t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const gateway=new MetaGateway({mainSessionId:'main',audit:path.join(dir,'gateway-audit.jsonl')});
 const hostFailure={code:'storage_write_error',stage:'logging',observed:{errorCode:'EACCES'}};
 assert.deepEqual(gateway.persistFinal({status:'error',hostFailure}).failure,hostFailure);
});

test('an earlier terminal model cause is not replaced by a later cleanup write failure',()=>{
 const model={code:'stream_whitespace',detectedAt:'2026-10-24T07:00:00.000Z'};
 const host={code:'storage_write_error',detectedAt:'2026-10-24T07:00:01.000Z'};
 const value=hostFailureDiagnostics({hostFailure:host},{failure:model});
 assert.equal(value.failure.code,'stream_whitespace');assert.deepEqual(value.failure.secondaryCodes,['storage_write_error']);
});

test('gateway audit write failure retains its first filesystem error during final diagnostics',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-audit-failure-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const audit=path.join(dir,'gateway-audit.jsonl'),append=fs.appendFileSync;
 t.mock.method(fs,'appendFileSync',(file,...args)=>{
  if(file===audit)throw Object.assign(new Error('Read-only filesystem'),{code:'EROFS'});
  return append(file,...args);
 });
 const g=new ModelGateway({model:{},audit});assert.throws(()=>g.record({type:'request'}),/Read-only/);
 const final=g.persistFinal({status:'error'});
 assert.equal(final.failure.code,'storage_write_error');assert.equal(final.failure.observed.errorCode,'EROFS');
 await assert.rejects(async()=>{for await(const chunk of g.stream({}))assert.fail('No provider call after audit failure');},e=>e.hostFailure.code==='storage_write_error');
});
