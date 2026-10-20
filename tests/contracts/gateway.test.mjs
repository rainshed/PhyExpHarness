import {budgetGate} from '../../src/execution/host/budget.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ModelGateway, providerRuntime } from '../../src/execution/host/model_gateway.mjs';
const model={provider:'openai-codex',model:'gpt-6-sol',reasoningEffort:'medium',maxTokens:8192};
test('native compaction inherits fixed reasoning and still enforces route, cap and accounting',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-compact-gateway-'));const seen=[],reserved=[],settled=[];
 const gateway=new ModelGateway({model,deadline:Date.now()+10000,audit:path.join(dir,'audit.jsonl'),
  reserve:async(id,request)=>reserved.push({id,request}),settle:async(id,result)=>settled.push({id,result}),
  adapter:{async *stream(request){seen.push(request);yield {type:'usage',usage:{inputTokens:10,outputTokens:2,totalTokens:12}};yield {type:'finish',reason:{kind:'stop'}};}}});
 try{
  const request={provider:model.provider,model:model.model,maxTokens:model.maxTokens,purpose:'compaction',sessionId:'native-session',messages:[]};
  for await(const _ of gateway.stream(request)){}
  assert.equal(seen[0].reasoningEffort,model.reasoningEffort);assert.equal(seen[0].sessionId,'native-session');
  assert.equal(request.reasoningEffort,undefined);assert.equal(reserved[0].request.reasoningEffort,model.reasoningEffort);
  assert.equal(settled[0].id,reserved[0].id);assert.equal(settled[0].result.usage.totalTokens,12);
  for(const key of ['provider','model','reasoningEffort','maxTokens'])await assert.rejects(async()=>{
   for await(const _ of gateway.stream({...request,[key]:key==='maxTokens'?65536:'other'})){}
  },/mismatch/);
  assert.equal(seen.length,1);assert.equal(reserved.length,1);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('context overflow retains a typed safe diagnostic instead of an undifferentiated provider error',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-context-failure-'));
 const gateway=new ModelGateway({model,deadline:Date.now()+10000,audit:path.join(dir,'audit.jsonl'),adapter:{async *stream(){
  yield {type:'finish',reason:{kind:'error',failure:{code:'CONTEXT_WINDOW_EXCEEDED',message:'raw adapter detail'}}};
 }}});
 try{for await(const _ of gateway.stream(model)){}
  assert.equal(gateway.firstFailure.code,'model_response_error');assert.equal(gateway.firstFailure.observed.providerCode,'CONTEXT_WINDOW_EXCEEDED');
  assert.ok(!JSON.stringify(gateway.firstFailure).includes('raw adapter detail'));
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('gateway enforces fixed route before provider use, records partial calls as unknown',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-gateway-'));let invoked=0,entries=[];
 const gateway=new ModelGateway({model,deadline:Date.now()+10000,audit:path.join(dir,'audit.jsonl'),
  adapter:{async *stream(){invoked++;yield {type:'text-delta',index:0,text:'partial'};throw new Error('disconnect');}},
  settle:async(id,result)=>entries.push(result)});
 try{
  for(const key of ['provider','model','reasoningEffort','maxTokens']) await assert.rejects(async()=>{for await(const _ of gateway.stream({...model,[key]:'other',messages:[]})){}},/mismatch/);
  assert.equal(invoked,0);
  await assert.rejects(async()=>{for await(const _ of gateway.stream({...model,messages:[]})){}},/disconnect/);
  assert.equal(entries[0].usage,null);assert.equal(invoked,1);
  assert.match(fs.readFileSync(path.join(dir,'audit.jsonl'),'utf8'),/unknown/);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
test('pi-ai host registration resolves the authorized models without a network call',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-provider-'));const file=path.join(dir,'empty.json');
 fs.writeFileSync(file,JSON.stringify({version:1,refs:{},records:{}}),{mode:0o600});
 try{for(const id of ['gpt-6-sol','gpt-6-astra']){const runtime=await providerRuntime({model:{...model,model:id},credentialFile:file});
  assert.equal(runtime.info.id,id);await runtime.dispose();}}
 finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('every extra call is reserved and settled; deadline and cancellation keep unknown usage',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-deadline-'));let reserves=0,settled=[];
 const gateway=new ModelGateway({model,deadline:Date.now()+100,audit:path.join(dir,'audit.jsonl'),reserve:async()=>{reserves++},settle:async(_,r)=>settled.push(r),
  adapter:{async *stream({signal}){await new Promise(resolve=>{if(signal.aborted)resolve();else signal.addEventListener('abort',resolve,{once:true});});throw new Error('cancelled');}}});
 await assert.rejects(async()=>{for await(const c of gateway.stream(model)){}},/cancel/);
 assert.equal(reserves,1);assert.equal(settled[0].usage,null);
 gateway.deadline=Date.now()-1; // Admission test uses an unambiguously expired clock, independent of timer rounding.
 await assert.rejects(async()=>{for await(const c of gateway.stream(model)){}},/deadline/);
 assert.equal(reserves,1);assert.equal(gateway.active.size,0);
 // A failed gateway must not admit another request; cancellation is tested on a fresh run.
 gateway.deadline=Date.now()+10000;await assert.rejects(async()=>{for await(const c of gateway.stream(model)){}},/trial_deadline/);
 const fresh=new ModelGateway({model,deadline:Date.now()+10000,audit:path.join(dir,'fresh.jsonl'),reserve:async()=>reserves++,settle:async(_,r)=>settled.push(r),adapter:gateway.adapter});const controller=new AbortController();
 const running=(async()=>{for await(const c of fresh.stream(model,controller.signal)){} })();
 controller.abort();await assert.rejects(running,/cancel/);assert.equal(reserves,2);assert.equal(settled.length,2);
 fs.rmSync(dir,{recursive:true,force:true});
});
test('provider transport error keeps reservation despite SDK synthetic zero usage',async()=>{
 const gate=budgetGate({deadline:Date.now()+10000,softTokenLimit:1000000});
 await gate.reserve('transport-error');await gate.settle('transport-error',{usage:{totalTokens:0},finish:{kind:'error'}});
 assert.equal(gate.snapshot().unknownReservedTokens,300000);assert.equal(gate.snapshot().confirmedTokens,0);
});

 test('null token cap preserves local metering and deadline enforcement',async()=>{
 const gate=budgetGate({deadline:Date.now()+10000,softTokenLimit:null});
 await gate.reserve('a');await gate.settle('a',{usage:{totalTokens:50000000},finish:{kind:'completed'}});
 await gate.reserve('b');assert.equal(gate.snapshot().confirmedTokens,50000000);assert.equal(gate.snapshot().softTokenLimit,null);
 const expired=budgetGate({deadline:Date.now()-1,softTokenLimit:null});await assert.rejects(()=>expired.reserve('c'),/Deadline/);
 });
