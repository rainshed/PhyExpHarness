import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {classifyModelFailure} from '../../src/execution/host/model_failures.mjs';
import {retryPlan} from '../../src/execution/runner/request_recovery.mjs';

const model={provider:'fixture',model:'fixture'},request={...model,messages:[]};
const policy={version:'solver-request-recovery-v1',retryDelaysSeconds:[2,5,20,30,60]};
async function setup(t,adapter){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-http-recovery-'));
 const server=http.createServer((req,res)=>{res.writeHead(Number(req.url.slice(1)),{'retry-after':'3'});res.end('{}');});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(async()=>{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));fs.rmSync(dir,{recursive:true,force:true});});
 const url=`http://127.0.0.1:${server.address().port}`;
 return new ModelGateway({model,deadline:Date.now()+10000,audit:path.join(dir,'audit.jsonl'),adapter:adapter(url)});
}
async function run(g,extra={}){const chunks=[];for await(const c of g.stream({...request,...extra}))chunks.push(c);return chunks;}
for(const thrown of [false,true])test('adapter-lost HTTP 503 joins existing bounded recovery; thrown='+thrown,async t=>{
 let calls=0;
 const g=await setup(t,url=>({async *stream(){
  if(calls++===0){await(await fetch(url+'/503',{method:'POST'})).text();
   const failure={code:'UNKNOWN',message:'An unspecified provider error'};
   if(thrown)throw Object.assign(new Error(failure.message),failure);
   yield {type:'finish',reason:{kind:'error',failure}};
  }else yield {type:'finish',reason:{kind:'stop'}};
 }}));
 let failure;
 if(thrown)await assert.rejects(run(g),error=>{failure=error.gatewayFailure;return true;});
 else failure=(await run(g)).at(-1).reason.failure;
 assert.equal(failure.code,'SERVER');assert.equal(failure.status,503);assert.equal(failure.providerRetryAfterMs,3000);
 assert.equal(g.firstFailure.code,'model_service_overloaded');assert.equal(g.terminalFailure,null);
 assert.equal(g.firstFailure.observed.statusSource,'request-transport');
 assert.deepEqual(retryPlan(policy,0,failure,10000,0),{retry:1,delayMs:3000});
 assert.equal(retryPlan(policy,5,failure,1000000,0).stop,'exhausted');
 assert.equal(retryPlan(policy,0,failure,3000,0).stop,'deadline');
 await run(g);
 assert.equal(g.diagnostics({status:'completed'}).failure,null);
 assert.equal(g.diagnostics().requestRecovery.recoveredRequests,1);
 assert.equal(calls,2);
});
test('concurrent logical requests do not borrow each other’s HTTP status',async t=>{
 const g=await setup(t,url=>({async *stream(r){
  await(await fetch(url+'/'+r.status,{method:'POST'})).text();
  yield {type:'finish',reason:{kind:'error',failure:{code:'UNKNOWN',message:'unspecified'}}};
 }}));
 const [a,b]=await Promise.all([run(g,{status:503}),run(g,{status:401})]);
 assert.equal(a.at(-1).reason.failure.code,'SERVER');
 assert.equal(b.at(-1).reason.failure.status,401);
 assert.equal(retryPlan(policy,0,b.at(-1).reason.failure,10000,0).stop,'ineligible');
});
test('ambiguous multi-HTTP request does not turn an unrelated 503 into a retry',async t=>{
 const g=await setup(t,url=>({async *stream(){
  await(await fetch(url+'/503')).text();await(await fetch(url+'/200')).text();
  yield {type:'finish',reason:{kind:'error',failure:{code:'UNKNOWN'}}};
 }}));
 const failure=(await run(g)).at(-1).reason.failure;
 assert.equal(failure.status,undefined);assert.equal(g.firstFailure.code,'model_response_error');
});
test('explicit client errors and nontransient adapter codes take precedence',()=>{
 for(const status of [400,401,403,429]){
  const normalized=classifyModelFailure({code:'TRANSPORT',message:'fetch failed',status},{status:503});
  assert.equal(normalized.failure.status,status);
  assert.equal(retryPlan(policy,0,normalized.failure,10000,0).stop,'ineligible');
  assert.equal(retryPlan(policy,0,{code:'TRANSPORT',status},10000,0).stop,'ineligible');
 }
 for(const code of ['CONTEXT_WINDOW_EXCEEDED','INVALID_CREDENTIAL','AUTHENTICATION']){
  const normalized=classifyModelFailure({code},{status:503});
  assert.equal(normalized.code,'model_response_error');
  assert.equal(retryPlan(policy,0,normalized.failure,10000,0).stop,'ineligible');
 }
});
