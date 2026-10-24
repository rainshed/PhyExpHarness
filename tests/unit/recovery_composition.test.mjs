import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {recoveryPolicy} from '../../src/execution/recovery/policy.mjs';
import {recoveryPlan,recoveryState,recordPrefix} from '../../src/execution/recovery/core.mjs';
import {StreamGuard} from '../../src/execution/host/stream_guard.mjs';
const policy=recoveryPolicy(JSON.parse(fs.readFileSync('recipes/h0-sol.json')).requestRecovery);
const model={provider:'fixture',model:'fixture'},request={...model,sessionId:'one',messages:[]};
async function collect(g,r=request){const chunks=[];for await(const chunk of g.stream(r))chunks.push(chunk);return chunks;}
function gateway(t,stream,extra={}){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'recovery-policy-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 return new ModelGateway({model,requestRecovery:policy,deadline:Date.now()+5000,audit:path.join(dir,'audit.jsonl'),adapter:{stream},policy:{cleanupGraceMs:1},...extra});
}
test('v2 validates composition and shared limits; v1 stays supported',()=>{
 assert.equal(recoveryPolicy({version:'solver-request-recovery-v1',retryDelaysSeconds:[2,5,20,30,60]}).version,'solver-request-recovery-v1');
 for(const change of [{strategies:['unknown']},{strategies:['transient-recovery','transient-recovery']},{maxChainRetries:0},{contentRetryDelaysSeconds:[-1]}])
  assert.throws(()=>recoveryPolicy({...policy,...change}),/Invalid/);
 const chain={transport:0,content:1,total:4};
 assert.equal(recoveryPlan(policy,chain,{category:'content'},{},1001,1).stop,'deadline');
 assert.equal(recoveryPlan(policy,{...chain,total:5},{category:'transport'},{},Infinity).stop,'chain_exhausted');
 assert.equal(recoveryPlan(policy,{...chain,content:2},{category:'content'},{},Infinity).stop,'exhausted');
 assert.equal(recoveryPlan(policy,chain,{category:'transport'},{providerRetryAfterMs:60000},60000,0).stop,'deadline');
});
test('projection preserves counts across step, turn and unrelated compaction boundaries',()=>{
 const chain={id:'a',transport:2,content:1,total:3,pendingFeedback:true};
 const events=[{type:recordPrefix+'state',data:{policy:policy.version,purpose:'step',chain}},
  {type:'step/start'},{type:'turn/end'},{type:'compaction/start'},
  {type:recordPrefix+'healthy',data:{policy:policy.version,purpose:'compaction'}}];
 assert.deepEqual(events.reduce(recoveryState,{step:null,compaction:null}),{step:chain,compaction:null});
});
test('host validates explicit chain lineage and never sends control metadata upstream',async t=>{
 let n=0;const g=gateway(t,async function*(r){assert.equal(r.phyexpRecovery,undefined);assert.equal(r.phyexpRecoveryScope,undefined);
  if(++n===1){yield {type:'tool-call-delta',index:0,argumentsDelta:'{"x":}'};return;}yield {type:'finish',reason:{kind:'stop'}};
 });
 let failure;await assert.rejects(collect(g),e=>{failure=e.gatewayFailure;return failure.code==='MODEL_OUTPUT_INVALID'&&failure.outputCode==='invalid_tool_arguments';});
 assert.equal(g.terminalFailure,null);
 await collect(g,{...request,messages:['unrelated']});assert.equal(g.diagnostics().requestRecovery.recoveredRequests,0);
 const phyexpRecovery={chainId:failure.recoveryChainId,parentRequestId:failure.requestId};
 await assert.rejects(collect(g,{...request,sessionId:'other',phyexpRecovery}),/Invalid recovery parent/);
 await assert.rejects(collect(g,{...request,purpose:'compaction',phyexpRecovery}),/Invalid recovery parent/);
 await collect(g,{...request,messages:['error feedback changes the history'],phyexpRecovery});
 assert.equal(g.diagnostics().requestRecovery.recoveredRequests,1);
 await assert.rejects(collect(g,{...request,phyexpRecovery}),/Invalid recovery parent/);
});
test('disabled output strategies retain terminal guard behavior',async t=>{
 const g=gateway(t,async function*(){yield {type:'tool-call-delta',index:0,argumentsDelta:'{"x":}'};},
  {requestRecovery:{...policy,strategies:['transient-recovery']}});
 await assert.rejects(collect(g),e=>e.gatewayFailure.code==='invalid_tool_arguments');
 assert.equal(g.terminalFailure.code,'invalid_tool_arguments');await assert.rejects(collect(g),/invalid_tool_arguments/);
});
test('oversized normalized end blocks cannot evade the streaming byte cap',()=>{
 const g=new StreamGuard({maxToolArgumentBytes:32});
 assert.equal(g.accept({type:'tool-call-delta',index:0,argumentsDelta:'{}'}),null);
 assert.equal(g.accept({type:'block-end',index:0,block:{type:'tool-call',arguments:JSON.stringify({x:'a'.repeat(40)})}}).code,'tool_argument_size_limit');
});
test('auxiliary calls cannot use the agent-only completed-argument feedback path',async t=>{
 const g=gateway(t,async function*(){yield {type:'block-end',index:0,block:{type:'tool-call',id:'bad',name:'tool',arguments:'{'}};yield {type:'finish',reason:{kind:'tool-calls'}};});
 await assert.rejects(collect(g,{...request,phyexpRecoveryScope:'direct'}),e=>e.gatewayFailure.code==='MODEL_OUTPUT_INVALID');
});
test('provider abortion cannot count as successful recovery',async t=>{
 let n=0;const g=gateway(t,async function*(){if(++n===1)throw Error('WebSocket error');yield {type:'finish',reason:{kind:'aborted'}};});
 let failure;await assert.rejects(collect(g),e=>{failure=e.gatewayFailure;return true;});
 await collect(g,{...request,phyexpRecovery:{chainId:failure.recoveryChainId,parentRequestId:failure.requestId}});
 assert.equal(g.diagnostics().requestRecovery.recoveredRequests,0);assert.equal(g.terminalFailure.code,'request_cancelled');
});
test('host independently caps repeated recovery references',async t=>{
 let calls=0;const g=gateway(t,async function*(){calls++;yield {type:'tool-call-delta',index:0,argumentsDelta:'{"x":}'};});
 let original;await assert.rejects(collect(g),e=>{original=e.gatewayFailure;return true;});
 const retry={...request,phyexpRecovery:{chainId:original.recoveryChainId,parentRequestId:original.requestId}};
 for(let i=0;i<2;i++)await assert.rejects(collect(g,retry),e=>e.gatewayFailure.code==='MODEL_OUTPUT_INVALID');
 await assert.rejects(collect(g,retry),e=>e.gatewayFailure.code==='RECOVERY_STOPPED');assert.equal(calls,3);
});
