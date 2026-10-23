import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {LlmError} from '@deepseek-ai/dsh-llm';
import {recoveryPolicy,retryPlan,recoveryState,cancellableDelay,recoverCompaction} from '../../src/execution/runner/request_recovery.mjs';
const policy=recoveryPolicy(JSON.parse(fs.readFileSync('recipes/h0-sol.json')).requestRecovery);
test('new baseline has exactly five waits; missing policy retains old behavior',()=>{
 assert.equal(recoveryPolicy(undefined),null);
 assert.deepEqual(policy.retryDelaysSeconds,[2,5,20,30,60]);
 assert.deepEqual(policy,JSON.parse(fs.readFileSync('recipes/h0-luna.json')).requestRecovery);
 assert.deepEqual(Array.from({length:5},(_,i)=>retryPlan(policy,i,{code:'TRANSPORT'},Infinity,0).delayMs),[2000,5000,20000,30000,60000]);
 assert.equal(retryPlan(policy,5,{code:'TRANSPORT'},Infinity).stop,'exhausted');
 assert.equal(retryPlan(null,0,{code:'TRANSPORT'},Infinity).stop,'ineligible');
 assert.equal(retryPlan(policy,0,{code:'SERVER',status:500,message:'Model provider returned an error'},Infinity).stop,'ineligible');
 for(const code of ['AUTHENTICATION','INVALID_CREDENTIAL','model_response_error','budget_admission_denied','trial_deadline','request_cancelled','request_timeout'])
  assert.equal(retryPlan(policy,0,{code},Infinity).stop,'ineligible');
 assert.throws(()=>recoveryPolicy({version:'unknown',retryDelaysSeconds:[2,5,20,30,60]}),/Invalid/);
});
test('server minimum delay and remaining wall clock cannot be bypassed',()=>{
 assert.equal(retryPlan(policy,0,{code:'SERVER',status:503,providerRetryAfterMs:120000},200000,0).delayMs,120000);
 assert.equal(retryPlan(policy,0,{code:'SERVER',status:503,providerRetryAfterMs:20},200000,0).delayMs,2000);
 assert.equal(retryPlan(policy,0,{code:'SERVER',status:503,providerRetryAfterMs:120000},120000,0).stop,'deadline');
 assert.equal(retryPlan(policy,0,{code:'TRANSPORT'},2100,100).stop,'deadline');
});
test('durable retry counters replay per step and compaction without influencing each other',()=>{
 const events=[{type:'step/start'},{type:'plugin:phyexp-request-recovery/scheduled',data:{purpose:'step',retry:2}},
  {type:'compaction/start'},{type:'plugin:phyexp-request-recovery/scheduled',data:{purpose:'compaction',retry:3}}];
 const restored=events.reduce(recoveryState,{step:0,compaction:0});
 assert.deepEqual(restored,{step:2,compaction:3});
 assert.deepEqual(recoveryState(restored,{type:'step/start'}),{step:0,compaction:3});
 assert.deepEqual(recoveryState(restored,{type:'turn/end'}),{step:0,compaction:0});
});
test('waiting can be cancelled immediately and leaves no timer running',async()=>{
 const c=new AbortController(),waiting=cancellableDelay(60000,c.signal);c.abort();
 assert.equal(await waiting,false);assert.equal(await cancellableDelay(60000,c.signal),false);
 assert.equal(await cancellableDelay(1,new AbortController().signal),true);
});
test('compaction retries the same request without leaking partial content or failed usage',async()=>{
 const options={purpose:'compaction',messages:[{content:'original'}]},seen=[];let calls=0,retries=0;
 const stream=async function*(request){seen.push(request);calls++;
  yield {type:'text-delta',index:0,text:calls<3?'broken':'complete'};
  yield {type:'usage',usage:{totalTokens:calls}};
  if(calls===1)throw new LlmError('connection interrupted','TRANSPORT');
  yield {type:'finish',reason:calls===2?{kind:'error',failure:{code:'SERVER',message:'overloaded'}}:{kind:'stop'}};
 };
 const result=[];for await(const c of recoverCompaction(stream,options,async failure=>{assert.ok(['SERVER','TRANSPORT'].includes(failure.code));retries++;return true;}))result.push(c);
 assert.equal(calls,3);assert.equal(retries,2);assert.ok(seen.every(r=>r===options));
 assert.equal(result[0].text,'complete');assert.deepEqual(result.filter(c=>c.type==='usage').map(c=>c.usage.totalTokens),[3]);
});
test('compaction propagates the final failure when recovery stops',async()=>{
 const error=new LlmError('invalid credentials','AUTHENTICATION');let calls=0;
 const stream=async function*(){calls++;throw error;};
 await assert.rejects(async()=>{for await(const c of recoverCompaction(stream,{},async()=>false))assert.fail(String(c));},e=>e===error);
 assert.equal(calls,1);
});
