import {budgetGate} from '../../src/execution/host/budget.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ModelGateway, providerRuntime } from '../../src/execution/host/model_gateway.mjs';
const model={provider:'openai-codex',model:'gpt-6-sol',reasoningEffort:'medium',maxTokens:8192};
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
 gateway.deadline=Date.now()+10000;const controller=new AbortController();
 const running=(async()=>{for await(const c of gateway.stream(model,controller.signal)){} })();
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
