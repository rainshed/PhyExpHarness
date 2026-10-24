import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {isolatedSession} from '../../src/execution/host/isolation.mjs';
import {recoveryState,recordPrefix} from '../../src/execution/recovery/core.mjs';
const model={provider:'openai-codex',model:'gpt-6-sol',reasoningEffort:'medium',maxTokens:8192};
const defaults=JSON.parse(fs.readFileSync('recipes/h0-sol.json')).requestRecovery;
const policy={...defaults,retryDelaysSeconds:[.001,.001,.001,.001,.001],contentRetryDelaysSeconds:[0,0]};
const plugin=`export const name='raw-tool-fixture';export const inject=['tools'];
export function apply(ctx){let calls=0;ctx.tools.register({name:'count_once',description:'Count a fixture side effect.',
 parameters:{type:'object',properties:{value:{type:'integer'}},required:['value']},
 output:{schema:{type:'string'},render:(_,v)=>[{type:'text',text:v}]},
 async execute(args){return 'action-count-'+(++calls)+'-value-'+args.value;}});}`;
function* call(id,args,{delta=true,finish=true}={}){
 yield {type:'block-start',index:0,blockType:'tool-call'};
 if(delta)yield {type:'tool-call-delta',index:0,id,name:'count_once',argumentsDelta:args};
 yield {type:'block-end',index:0,block:{type:'tool-call',id,name:'count_once',arguments:args}};
 if(finish)yield {type:'finish',reason:{kind:'tool-calls'}};
}
function* done(){yield {type:'block-start',index:0,blockType:'text'};yield {type:'block-end',index:0,block:{type:'text',text:'completed'}};yield {type:'finish',reason:{kind:'stop'}};}
async function fixture(run,{recovery=policy,streamPolicy={},fixturePlugin=plugin,deadlineOffset=30000,cancelWait=false}={}){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-recovery-v2-')),plugins=path.join(dir,'plugins');fs.mkdirSync(plugins);
 fs.writeFileSync(path.join(plugins,'fixture.mjs'),fixturePlugin);
 const seen=[],settled=[];let receipt;
 const gateway=new ModelGateway({model,deadline:Date.now()+30000,audit:path.join(dir,'gateway.jsonl'),requestRecovery:recovery,
  policy:{cleanupGraceMs:5,...streamPolicy},settle:async(id,result)=>settled.push({id,...result}),
  adapter:{async *stream(request){assert.equal(request.phyexpRecovery,undefined);seen.push(request);yield* run(seen.length,request);}}});
 const session=isolatedSession({executionRoot:'src/execution',logs:dir,gateway,
  config:{requestRecovery:recovery,recoveryDeadline:Date.now()+deadlineOffset,disableLocalTools:true,fixedModel:model,
   modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},
   plugins:[{id:'fixture',name:'/opt/phyexp/plugins/fixture.mjs'}]},
  mounts:[`type=bind,source=${plugins},target=/opt/phyexp/plugins,readonly`],async *handler(op,payload){assert.equal(op,'receipt');receipt=payload;yield {ok:true};}});
 try{
  await session.request('initialize',{...model,cwd:'/tmp/work'});
  const pending=session.prompt('recovery-v2','Run the fixture.',25000);pending.catch(()=>{});
  if(cancelWait){
   const until=Date.now()+5000;
   while(!session.messages.some(m=>m.params?.event?.type===recordPrefix+'scheduled')){
    assert.ok(Date.now()<until,'recovery wait did not start');await new Promise(r=>setTimeout(r,10));
   }
   await session.shutdown();await pending.catch(()=>{});
   return {seen,settled,events:session.messages.filter(m=>m.method==='session.event').map(m=>m.params.event)};
  }
  const events=await pending,reason=events.filter(e=>e.type==='turn/end').at(-1).data.reason;
  const summary=gateway.persistFinal({status:reason.kind==='completed'?'completed':'error',turnEnd:reason});
  await session.shutdown();return {seen,settled,events,reason,summary,receipt,gateway};
 }catch(error){throw new Error(error.stack+'\n'+fs.readFileSync(path.join(dir,'stderr.log'),'utf8'));}
 finally{await session.dispose();console.log('Recovery composition evidence: '+dir);}
}
test('mixed content, connection and feedback recovery share one chain and preserve tools',{timeout:40000},async()=>{
 const result=await fixture(async function*(n,request){
  if(n===1){yield* call('before','{"value":1}');return;}
  if(n===2){yield* call('partial','{"value":}');return;}
  if(n===3)throw Error('WebSocket error');
  if(n===4){yield* call('bad-complete','{"value":');return;}
  if(n===5){
   const history=JSON.stringify(request.messages);assert.match(history,/action-count-1-value-1/);assert.match(history,/Invalid tool arguments/);
   assert.ok(!history.includes('partial'));yield* call('corrected','{"value":2}');return;
  }
  assert.equal(n,6);assert.match(JSON.stringify(request.messages),/action-count-2-value-2/);yield* done();
 });
 assert.equal(result.reason.kind,'completed');assert.equal(result.seen.length,6);assert.equal(result.settled.length,6);
 const scheduled=result.events.filter(e=>e.type===recordPrefix+'scheduled').map(e=>e.data);
 assert.deepEqual(scheduled.map(d=>d.strategy),['response-recovery','transient-recovery','tool-argument-recovery']);
 assert.deepEqual(scheduled.map(d=>d.chainRetry),[1,2,3]);assert.equal(new Set(scheduled.map(d=>d.recoveryChainId)).size,1);
 assert.equal(result.summary.requestRecovery.failedRequests,3);assert.equal(result.summary.requestRecovery.recoveredRequests,3);
 assert.equal(result.summary.failure,null);
 assert.deepEqual(result.receipt.recoveryComposition.strategies,defaults.strategies);
 assert.deepEqual(result.events.reduce(recoveryState,{step:null,compaction:null}),{step:null,compaction:null});
});
for(const args of ['{','{"value":"wrong"}',''])test('complete invalid arguments stop after two corrections without invoking a raw tool: '+JSON.stringify(args),{timeout:40000},async()=>{
 const result=await fixture(async function*(){yield* call('bad',args,{delta:false});});
 assert.equal(result.reason.kind,'error');assert.equal(result.seen.length,3);
 assert.ok(result.events.filter(e=>e.type==='tool/result').every(e=>!JSON.stringify(e).includes('action-count')));
 const state=result.events.reduce(recoveryState,{step:null,compaction:null}).step;
 assert.equal(state.content,2);assert.equal(state.total,2);assert.equal(state.stopped,'exhausted');
 assert.equal(result.summary.requestRecovery.recoveredRequests,0);
 assert.equal(result.summary.failure.requestId,result.settled.at(-1).id);
});
test('aggregate limit owns exhaustion across strategy changes',{timeout:40000},async()=>{
 const result=await fixture(async function*(n){
  if(n===1){yield* call('bad','{',{delta:false});return;}
  throw Error('WebSocket error');
 },{recovery:{...policy,maxChainRetries:2}});
 assert.equal(result.seen.length,3);assert.equal(result.reason.kind,'error');
 assert.equal(result.events.filter(e=>e.type===recordPrefix+'stopped').at(-1).data.reason,'chain_exhausted');
});
test('missing terminal receipt never executes a completed tool block',{timeout:40000},async()=>{
 const result=await fixture(async function*(n){
  if(n===1){yield* call('lost','{"value":1}',{finish:false});return;}
  if(n===2){yield* call('actual','{"value":1}');return;}yield* done();
 });
 assert.equal(result.reason.kind,'completed');assert.equal(result.seen.length,3);
 assert.equal(result.events.filter(e=>e.type==='tool/call').length,1);
 assert.equal(result.summary.requestRecovery.recoveredRequests,1);
});
test('removing feedback strategy routes complete invalid arguments to request regeneration',{timeout:40000},async()=>{
 const result=await fixture(async function*(n){if(n===1){yield* call('discarded','{',{delta:false});return;}yield* done();},
  {recovery:{...policy,strategies:['transient-recovery','response-recovery']}});
 assert.equal(result.reason.kind,'completed');assert.equal(result.seen.length,2);
 assert.equal(result.events.filter(e=>e.type==='tool/call').length,0);
 assert.equal(result.events.find(e=>e.type===recordPrefix+'scheduled').data.strategy,'response-recovery');
});
test('v2 cancellation interrupts a pending wait without a second request',{timeout:40000},async()=>{
 const result=await fixture(async function*(){throw Error('WebSocket error');},{recovery:{...policy,retryDelaysSeconds:[10,10,10,10,10]},cancelWait:true});
 assert.equal(result.seen.length,1);assert.equal(result.events.filter(e=>e.type===recordPrefix+'started').length,0);
});
test('v2 refuses a wait that would exceed the original deadline',{timeout:40000},async()=>{
 const result=await fixture(async function*(){throw Error('WebSocket error');},{recovery:{...policy,retryDelaysSeconds:[10,10,10,10,10]},deadlineOffset:5000});
 assert.equal(result.seen.length,1);assert.equal(result.reason.kind,'error');
 assert.equal(result.events.filter(e=>e.type===recordPrefix+'stopped').at(-1).data.reason,'deadline');
});
const auxiliaryPlugin=`export const name='auxiliary-fixture';export const inject=['tools','llm'];
export function apply(ctx){ctx.tools.register({name:'auxiliary',description:'Call an auxiliary model request.',parameters:{type:'object'},
 output:{schema:{type:'string'},render:(_,v)=>[{type:'text',text:v}]},async execute(args,exec){
 let text='';for await(const chunk of ctx.llm.stream({...JSON.parse(process.env.PHYEXP_FIXED_MODEL),
  sessionId:exec.agent.session.id,signal:exec.signal,...(args.compaction?{purpose:'compaction'}:{}),messages:[]})){
  if(chunk.type==='text-delta')text+=chunk.text;
 }return 'auxiliary-result:'+text;}});}`;
test('compaction retries atomically with its own chain in the real runtime',{timeout:40000},async()=>{
 let compactions=0;
 const result=await fixture(async function*(n,request){
  if(request.purpose==='compaction'){
   compactions++;yield {type:'block-start',index:0,blockType:'text'};
   yield {type:'text-delta',index:0,text:compactions===1?'discarded-partial':'complete-summary'};
   if(compactions===1)throw Error('WebSocket error');
   yield {type:'block-end',index:0,block:{type:'text',text:'complete-summary'}};yield {type:'finish',reason:{kind:'stop'}};return;
  }
  if(n===1){yield {type:'block-start',index:0,blockType:'tool-call'};
   yield {type:'block-end',index:0,block:{type:'tool-call',id:'summary',name:'auxiliary',arguments:'{"compaction":true}'}};
   yield {type:'finish',reason:{kind:'tool-calls'}};return;}
  const history=JSON.stringify(request.messages);assert.match(history,/auxiliary-result:complete-summary/);assert.ok(!history.includes('discarded-partial'));yield* done();
 },{fixturePlugin:auxiliaryPlugin});
 assert.equal(compactions,2);assert.equal(result.reason.kind,'completed');
 assert.equal(result.events.find(e=>e.type===recordPrefix+'scheduled').data.purpose,'compaction');
 assert.equal(result.summary.requestRecovery.recoveredRequests,1);
});
test('a successful auxiliary request cannot reset an outstanding tool-feedback chain',{timeout:40000},async()=>{
 const result=await fixture(async function*(n,request){
  if(n===2){yield* done();return;}
  if(n===1){
   yield* call('bad','{',{delta:false,finish:false});
   yield {type:'block-start',index:1,blockType:'tool-call'};
   yield {type:'block-end',index:1,block:{type:'tool-call',id:'aux',name:'auxiliary',arguments:'{}'}};
   yield {type:'finish',reason:{kind:'tool-calls'}};return;
  }
  assert.match(JSON.stringify(request.messages),/auxiliary-result/);yield* call('bad-'+n,'{',{delta:false});
 },{fixturePlugin:plugin.replace("export const name='raw-tool-fixture';",'').replace("export const inject=['tools'];",'').replace('export function apply(ctx)', 'function registerRaw(ctx)')+'\n'+auxiliaryPlugin.replace('export function apply(ctx){','export function apply(ctx){registerRaw(ctx);')});
 assert.equal(result.seen.length,4);assert.equal(result.reason.kind,'error');
 assert.equal(result.events.filter(e=>e.type===recordPrefix+'scheduled').length,2);
 assert.equal(result.summary.requestRecovery.recoveredRequests,0);
});
for(const code of ['stream_whitespace','tool_argument_size_limit','response_size_limit'])
 test('native output recovery retains protection: '+code,{timeout:40000},async()=>{
  const result=await fixture(async function*(n){
   if(n===1){
    if(code==='response_size_limit')yield {type:'text-delta',index:0,text:'x'.repeat(40)};
    else yield {type:'tool-call-delta',index:0,id:'bad',name:'count_once',argumentsDelta:'{"value":"'+(code==='stream_whitespace'?' '.repeat(4096):'x'.repeat(80))};
    return;
   }
   yield* done();
  },{streamPolicy:code==='stream_whitespace'?{whitespaceMinMs:0}:code==='tool_argument_size_limit'?{maxToolArgumentBytes:64}:{maxResponseBytes:32}});
  assert.equal(result.reason.kind,'completed');assert.equal(result.seen.length,2);
  assert.equal(result.events.filter(e=>e.type==='tool/call').length,0);
  assert.equal(result.summary.requestRecovery.failures[0].code,code);
  assert.equal(result.summary.requestRecovery.recoveredRequests,1);
 });
test('exhausted coordinator does not delegate an owned error to a candidate retry plugin',{timeout:40000},async()=>{
 const candidate=plugin.replace('export function apply(ctx){',"export function apply(ctx){ctx.on('agent/request-error',()=>{throw Error('candidate must not intercept');});");
 const result=await fixture(async function*(){throw Error('WebSocket error');},{fixturePlugin:candidate,recovery:{...policy,maxChainRetries:1}});
 assert.equal(result.reason.kind,'error');assert.equal(result.seen.length,2);
 assert.equal(result.reason.error.code,'TRANSPORT');
 assert.equal(result.events.filter(e=>e.type===recordPrefix+'stopped').at(-1).data.reason,'chain_exhausted');
});
