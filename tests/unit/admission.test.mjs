import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {budgetGate} from '../../src/execution/host/budget.mjs';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';

const model={provider:'openai-codex',model:'gpt-6-luna',reasoningEffort:'xhigh'};
async function fixture(t,handle){
 const server=http.createServer(async(req,res)=>{
  let body='';for await(const chunk of req)body+=chunk;
  const response=await handle(req.url,JSON.parse(body));
  if(response.drop){req.socket.destroy();return;}
  res.writeHead(response.code||200,{'content-type':'application/json'});res.end(response.raw??JSON.stringify(response.body));
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve)}));
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-admission-'));t.after(()=>fs.rmSync(folder,{recursive:true,force:true}));
 return {url:`http://127.0.0.1:${server.address().port}`,audit:path.join(folder,'audit.jsonl')};
}
for(const waitCode of ['budget_inflight_wait','storage_capacity_wait'])test(waitCode+' uses one request identity and calls no provider until granted',async t=>{
 let attempts=0,calls=0,settles=0;const ids=[];
 const f=await fixture(t,(url,body)=>{
  if(url==='/settle'){settles++;return {body:{status:'reported'}}}
  attempts++;ids.push(body.id);assert.equal(body.admissionVersion,1);
  return attempts<3?{code:429,body:{status:'waiting',code:waitCode,retryAfterMs:20}}:{body:{status:'granted'}};
 });
 const gate=budgetGate({deadline:Date.now()+5000,softTokenLimit:null,url:f.url,token:'fixture'});
 const gateway=new ModelGateway({model,deadline:Date.now()+5000,audit:f.audit,reserve:gate.reserve,settle:gate.settle,
  policy:{streamIdleTimeoutMs:10},adapter:{async *stream(){calls++;assert.equal(attempts,3);yield {type:'usage',usage:{totalTokens:3}};yield {type:'finish',reason:{kind:'stop'}};}}});
 for await(const _ of gateway.stream({...model,messages:[]})){}
 assert.equal(calls,1);assert.equal(settles,1);assert.equal(new Set(ids).size,1);
 assert.equal(gateway.diagnostics({status:'completed'}).requestRecovery.failedRequests,0);
 assert.match(fs.readFileSync(f.audit,'utf8'),/admission_waiting/);
});
test('budget denial has typed audit and no false provider request',async t=>{
 const f=await fixture(t,()=>({code:403,body:{status:'denied',code:'budget_admission_denied',boundary:'configured_limit',observed:{confirmedTokens:100}}}));
 const gate=budgetGate({deadline:Date.now()+5000,url:f.url});
 let calls=0;const gateway=new ModelGateway({model,deadline:Date.now()+5000,audit:f.audit,reserve:gate.reserve,
  adapter:{async *stream(){calls++;}}});
 await assert.rejects(async()=>{for await(const _ of gateway.stream({...model,messages:[]})){}},e=>e.gatewayFailure.code==='budget_admission_denied');
 assert.equal(calls,0);const d=gateway.persistFinal({status:'error'});
 assert.equal(d.failure.stage,'admission');assert.equal(d.failure.code,'budget_admission_denied');
 assert.equal(d.requestRecovery.failedRequests,0);
 const events=fs.readFileSync(f.audit,'utf8').trim().split('\n').map(JSON.parse);
 assert.ok(events.some(e=>e.type==='admission_denied'));assert.ok(!events.some(e=>e.type==='request'));
});
test('gateway cancellation interrupts admission waiting without provider retries',async t=>{
 const f=await fixture(t,()=>({code:429,body:{status:'waiting',code:'budget_plan_wait',retryAfterMs:1000}}));
 const gate=budgetGate({deadline:Date.now()+5000,url:f.url});
 const gateway=new ModelGateway({model,deadline:Date.now()+5000,audit:f.audit,reserve:gate.reserve,adapter:{async *stream(){assert.fail('provider called')}}});
 const pending=(async()=>{for await(const _ of gateway.stream({...model,messages:[]})){} })();
 const timer=setTimeout(()=>gateway.abort(),30);t.after(()=>clearTimeout(timer));
 await assert.rejects(pending,e=>e.gatewayFailure.code==='request_cancelled');
 assert.equal(gate.snapshot().inflightReservedTokens,0);
});
test('lease authentication and broken accounting transport remain platform errors',async t=>{
 const f=await fixture(t,()=>({code:401,body:{error:'Lease expired',code:'accounting_lease_expired'}}));
 const gate=budgetGate({deadline:Date.now()+5000,url:f.url});
 await assert.rejects(()=>gate.reserve('expired'),e=>e.admissionFailure.code==='accounting_lease_expired');
 const broken=budgetGate({deadline:Date.now()+100,url:'http://127.0.0.1:1',accountingRetryMs:5});
 await assert.rejects(()=>broken.reserve('offline'),e=>e.admissionFailure.code==='trial_deadline'&&e.admissionFailure.lastAccountingFailure.code==='accounting_unavailable');
});

for(const outage of ['lost response','timeout','busy'])test('ledger '+outage+' preserves reservation identity and invokes provider once',async t=>{
 const reservations=new Set(),ids=[];let attempts=0,calls=0;
 const f=await fixture(t,async(url,body)=>{
  if(url==='/settle')return {body:{status:'reported'}};
  ids.push(body.id);reservations.add(body.id);
  if(++attempts===1){
   if(outage==='lost response')return {drop:true};
   if(outage==='busy')return {code:503,raw:'temporarily busy'};
   await new Promise(resolve=>setTimeout(resolve,150));
  }
  return {body:{status:'granted'}};
 });
 const gate=budgetGate({deadline:Date.now()+3000,url:f.url,accountingTimeoutMs:70,accountingRetryMs:5});
 const gateway=new ModelGateway({model,deadline:Date.now()+3000,audit:f.audit,reserve:gate.reserve,settle:gate.settle,
  adapter:{async *stream(){calls++;assert.ok(attempts>=2);yield {type:'usage',usage:{totalTokens:3}};yield {type:'finish',reason:{kind:'stop'}};}}});
 for await(const _ of gateway.stream({...model,messages:[]})){}
 assert.equal(calls,1);assert.equal(reservations.size,1);assert.equal(new Set(ids).size,1);
 assert.equal(gate.snapshot().confirmedTokens,3);assert.equal(gate.snapshot().unknownReservedTokens,0);
 assert.equal(gateway.terminalFailure,null);
 const events=fs.readFileSync(f.audit,'utf8').trim().split('\n').map(JSON.parse);
 assert.ok(events.some(e=>e.type==='admission_waiting'&&e.code==='accounting_unavailable'));
 assert.ok(!events.some(e=>e.type==='admission_denied'));
});

test('lost settlement is replayed before next admission without counting or executing it twice',async t=>{
 const records=new Map();let settlementAttempts=0,calls=0;
 const f=await fixture(t,(url,body)=>{
  if(url==='/settle'){
   records.set(body.id,body.confirmedTokens);
   if(++settlementAttempts<=2)return {drop:true};
   return {body:{status:'reported'}};
  }
  if(calls)assert.ok(settlementAttempts>=3,'settlement must recover before next reservation');
  return {body:{status:'granted'}};
 });
 const gate=budgetGate({deadline:Date.now()+3000,url:f.url,accountingRetryMs:5});
 const gateway=new ModelGateway({model,deadline:Date.now()+3000,audit:f.audit,reserve:gate.reserve,settle:gate.settle,
  adapter:{async *stream(){calls++;yield {type:'usage',usage:{totalTokens:3}};yield {type:'finish',reason:{kind:'stop'}};}}});
 for await(const _ of gateway.stream({...model,messages:[]})){}
 assert.equal(gate.snapshot().pendingSettlementRequests,1);
 for await(const _ of gateway.stream({...model,messages:[]})){}
 assert.equal(calls,2);assert.equal(records.size,2);assert.equal(gate.snapshot().confirmedTokens,6);
 assert.equal(gate.snapshot().pendingSettlementRequests,0);
 assert.match(fs.readFileSync(f.audit,'utf8'),/settlement_pending/);
});

test('cancellation interrupts unavailable accounting and retains finite local reservations while waiting',async t=>{
 const f=await fixture(t,()=>({code:503,raw:'busy'}));const stop=new AbortController();let observed=false;
 const gate=budgetGate({deadline:Date.now()+5000,url:f.url,softTokenLimit:300000,accountingRetryMs:5});
 await assert.rejects(()=>gate.reserve('cancelled',{}, {signal:stop.signal,onState:()=>{
  observed=true;assert.equal(gate.snapshot().inflightReservedTokens,300000);stop.abort();
 }}),e=>e.code==='request_cancelled');
 assert.ok(observed);assert.equal(gate.snapshot().inflightReservedTokens,0);
});

for(const response of [{code:401,body:{code:'accounting_auth_failed'}},{code:200,raw:'invalid JSON'},
 {code:409,body:{error:'identity conflict'}}])test('permanent accounting error is not retried: '+response.code,async t=>{
 let calls=0;const f=await fixture(t,()=>{calls++;return response;});
 const gate=budgetGate({deadline:Date.now()+2000,url:f.url});
 await assert.rejects(()=>gate.reserve('request'),e=>['accounting_auth_failed','accounting_protocol_error'].includes(e.code));
 assert.equal(calls,1);
});
