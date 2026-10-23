import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {classifyModelFailure} from '../../src/execution/host/model_failures.mjs';
import {budgetGate} from '../../src/execution/host/budget.mjs';
const model={provider:'fixture',model:'fixture'};
const request={...model,sessionId:'one',messages:[]};
async function run(g,r=request){const chunks=[];for await(const c of g.stream(r))chunks.push(c);return chunks;}
function setup(t,adapter,options={}){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-recovery-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));return new ModelGateway({model,adapter,deadline:Date.now()+10000,audit:path.join(dir,'audit.jsonl'),...options});}
test('only supported provider evidence identifies overload or transport; safe facts preserve retry delay',()=>{
 assert.equal(classifyModelFailure(null).code,'model_response_error');
 assert.equal(classifyModelFailure({code:'PI_AI_ERROR',message:'Codex error: Our servers are currently overloaded. Please try again later.'}).code,'model_service_overloaded');
 assert.equal(classifyModelFailure({code:'PI_AI_ERROR',message:'WebSocket error'}).failure.code,'TRANSPORT');
 for(const message of ['WebSocket closed 1012 service restart','WebSocket closed 1006','WebSocket connection timed out']){
  assert.equal(classifyModelFailure({code:'PI_AI_ERROR',message}).code,'model_transport_error');
 }
 assert.deepEqual(classifyModelFailure({code:'SERVER',status:503,providerRetryAfterMs:1234}).failure,{code:'SERVER',message:'Model service overloaded',status:503,providerRetryAfterMs:1234});
 for(const x of [{code:'AUTH',message:'invalid key SECRET'},{code:'PI_AI_ERROR',message:'unspecified'},{code:'CONTEXT_WINDOW_EXCEEDED'}]){
  const value=classifyModelFailure(x);assert.equal(value.code,'model_response_error');assert.ok(!JSON.stringify(value).includes('SECRET'));
 }
});
test('recoverable attempts do not latch; matching recovery and terminal diagnostics are independent',async t=>{
 let calls=0;const settled=[];const g=setup(t,{async *stream(){calls++;if(calls===1)yield {type:'finish',reason:{kind:'error',failure:{code:'PI_AI_ERROR',message:'WebSocket error'}}};else yield {type:'finish',reason:{kind:'stop'}};}},{settle:async(id,r)=>settled.push({id,...r})});
 const chunks=await run(g);const failure=chunks.at(-1).reason.failure;
 assert.equal(g.terminalFailure,null);assert.equal(g.firstFailure.code,'model_transport_error');
 assert.equal(g.diagnostics({status:'error',turnEnd:{kind:'error',error:failure}}).failure.requestId,failure.requestId);
 await run(g,{...request,sessionId:'unrelated'});assert.equal(g.diagnostics().requestRecovery.recoveredRequests,0);
 await run(g);assert.equal(g.diagnostics().requestRecovery.recoveredRequests,1);assert.equal(settled.length,3);
 const final=g.persistFinal({status:'completed',turnEnd:{kind:'completed'}});assert.equal(final.failure,null);
 assert.equal(final.requestRecovery.failedRequests,1);assert.equal(JSON.parse(fs.readFileSync(path.join(path.dirname(g.audit),'failure.json'))).failure,null);
});
test('different concurrent request completion cannot recover a failure that occurred after it started',async t=>{
 let finish;const signal=new Promise(r=>finish=r);let calls=0;
 const g=setup(t,{async *stream(){if(++calls===1){await signal;yield {type:'finish',reason:{kind:'stop'}};}else{yield {type:'finish',reason:{kind:'error',failure:{code:'TRANSPORT',message:'disconnect'}}};}}});
 const first=run(g);await new Promise(r=>setTimeout(r,5));await run(g);finish();await first;
 assert.equal(g.diagnostics().requestRecovery.recoveredRequests,0);
});
test('each retry is metered and unknown failed usage continues to consume admission budget',async t=>{
 const budget=budgetGate({deadline:Date.now()+10000,softTokenLimit:600000});let calls=0;
 const g=setup(t,{async *stream(){calls++;yield {type:'usage',usage:{totalTokens:0}};yield {type:'finish',reason:{kind:'error',failure:{code:'TRANSPORT',message:'disconnect'}}};}},{reserve:budget.reserve,settle:budget.settle});
 await run(g);await run(g);await assert.rejects(run(g),/threshold/);assert.equal(calls,2);
 assert.equal(budget.snapshot().unknownReservedTokens,600000);
 assert.equal(g.diagnostics().requestRecovery.failedRequests,2);
});
test('cancel, expired deadline and fixed route remain authoritative after a recoverable failure',async t=>{
 let calls=0;const g=setup(t,{async *stream(){calls++;throw Error('WebSocket error');}});
 await assert.rejects(run(g),/WebSocket/);
 await assert.rejects(run(g,{...request,model:'another'}),/mismatch/);
 g.deadline=Date.now()-1;await assert.rejects(run(g),/deadline/);g.deadline=Date.now()+1000;
 g.abort();await assert.rejects(run(g),/cancelled/);assert.equal(calls,1);
});
test('cancellation during asynchronous budget reservation cannot start a provider request',async t=>{
 let reserved,release;const entered=new Promise(r=>reserved=r),waiting=new Promise(r=>release=r);let calls=0,settled=0;
 const g=setup(t,{async *stream(){calls++;yield {type:'finish',reason:{kind:'stop'}};}},{reserve:async()=>{reserved();await waiting;},settle:async()=>settled++});
 const running=run(g);await entered;g.abort();release();await assert.rejects(running,/cancelled/);
 assert.equal(calls,0);assert.equal(settled,1);
});
test('missing stream receipt is recoverable and final failure points to the last unsuccessful step',async t=>{
 let calls=0;const g=setup(t,{async *stream(){calls++;if(calls===1)return;yield {type:'finish',reason:{kind:'error',failure:{code:'SERVER',status:503,message:'overloaded'}}};}});
 let first;await assert.rejects(run(g),e=>{first=e.gatewayFailure;return first.code==='TRANSPORT';});
 const second=(await run(g)).at(-1).reason.failure;
 const final=g.persistFinal({status:'error',turnEnd:{kind:'error',error:second}});
 assert.equal(final.failure.requestId,second.requestId);assert.notEqual(final.failure.requestId,first.requestId);
 assert.equal(final.failure.code,'model_service_overloaded');assert.equal(final.requestRecovery.failedRequests,2);
});
for(const thrown of [false,true])test('context overflow permits native compaction and only a resumed success counts as recovery: '+thrown,async t=>{
 let calls=0;const settled=[];const g=setup(t,{async *stream(){
  if(calls++===0){if(thrown)throw Object.assign(new Error('context too large'),{code:'CONTEXT_WINDOW_EXCEEDED'});yield {type:'finish',reason:{kind:'error',failure:{code:'CONTEXT_WINDOW_EXCEEDED'}}};}
  else yield {type:'finish',reason:{kind:'stop'}};
 }},{settle:async(id,result)=>settled.push({id,result})});
 if(thrown)await assert.rejects(run(g),error=>error.gatewayFailure.code==='CONTEXT_WINDOW_EXCEEDED');else assert.equal((await run(g)).at(-1).reason.failure.code,'CONTEXT_WINDOW_EXCEEDED');
 assert.equal(g.terminalFailure,null);
 await run(g,{...request,purpose:'compaction',sessionId:'other'});
 await run(g,{...request,messages:['changed']});assert.equal(g.diagnostics().requestRecovery.recoveredRequests,0);
 await run(g,{...request,purpose:'compaction'});assert.equal(g.diagnostics().requestRecovery.recoveredRequests,0);
 await run(g,{...request,messages:['summary']});assert.equal(g.diagnostics().requestRecovery.recoveredRequests,1);assert.equal(settled.length,5);
 await assert.rejects(run(g,{...request,model:'wrong'}),/mismatch/);g.abort();await assert.rejects(run(g),/cancelled/);
});
test('authentication failure still prevents subsequent compaction calls',async t=>{
 const g=setup(t,{async *stream(){yield {type:'finish',reason:{kind:'error',failure:{code:'INVALID_CREDENTIAL'}}};}});
 await run(g);assert.equal(g.terminalFailure.code,'model_response_error');await assert.rejects(run(g,{...request,purpose:'compaction'}),/model_response_error/);
});
