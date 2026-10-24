import test from 'node:test';import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {isolatedSession} from '../../src/execution/host/isolation.mjs';
import {budgetGate} from '../../src/execution/host/budget.mjs';
const model={provider:'openai-codex',model:'gpt-6-sol',reasoningEffort:'medium',maxTokens:8192};
const plugin=`import {defineTool} from '@deepseek-ai/dsh-tools';
export const name='recovery-fixture';export const inject=['tools'];
export function apply(ctx){let calls=0;
 ctx.tools.register(defineTool({name:'count_once',description:'Count an irreversible fixture action.',parameters:{},output:{schema:{type:'string'},render:(_,v)=>[{type:'text',text:v}]},async execute(){return 'action-count-'+(++calls);}}));

}`;
const policy={version:'solver-request-recovery-v1',retryDelaysSeconds:[2,5,20,30,60]};
test('new baseline recovers failed steps, preserves completed tools, and resets its delay per step',{timeout:45000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-native-recovery-'));const plugins=path.join(dir,'plugins');fs.mkdirSync(plugins);fs.writeFileSync(path.join(plugins,'fixture.mjs'),plugin);
 let calls=0;const settled=[];const reserves=[];
 const gateway=new ModelGateway({model,deadline:Date.now()+35000,audit:path.join(dir,'gateway.jsonl'),reserve:async id=>reserves.push(id),settle:async(id,r)=>settled.push({id,...r}),
  adapter:{async *stream(request){calls++;
   if(calls<=2){yield {type:'finish',reason:{kind:'error',failure:{code:'PI_AI_ERROR',message:'Our servers are currently overloaded. Please try again later.',providerRetryAfterMs:20}}};return;}
   if(calls===3||calls===4){
    yield {type:'block-start',index:0,blockType:'tool-call'};
    yield {type:'tool-call-delta',index:0,id:'action-'+calls,name:'count_once',argumentsDelta:calls===3?'{}':'{"partial":'};
    if(calls===4)throw Error('WebSocket error');
    yield {type:'block-end',index:0,block:{type:'tool-call',id:'action-3',name:'count_once',arguments:'{}'}};
    yield {type:'finish',reason:{kind:'tool-calls'}};return;
   }
   const history=JSON.stringify(request.messages);assert.match(history,/action-count-1/);assert.ok(!history.includes('partial'));assert.ok(!history.includes('action-4'));
   yield {type:'block-start',index:0,blockType:'text'};yield {type:'text-delta',index:0,text:'completed'};yield {type:'block-end',index:0,block:{type:'text',text:'completed'}};
   yield {type:'usage',usage:{totalTokens:12,inputTokens:10,outputTokens:2}};yield {type:'finish',reason:{kind:'stop'}};
  }}});
 const session=isolatedSession({executionRoot:'src/execution',logs:dir,gateway,config:{requestRecovery:policy,recoveryDeadline:gateway.deadline,disableLocalTools:true,fixedModel:model,modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},plugins:[{id:'fixture',name:'/opt/phyexp/plugins/fixture.mjs'}]},mounts:[`type=bind,source=${plugins},target=/opt/phyexp/plugins,readonly`],async *handler(op){assert.equal(op,'receipt');yield {ok:true};}});
 try{await session.request('initialize',{...model,cwd:'/tmp/work'});
  const events=await session.prompt('recovery-fixture','Execute count_once once, then finish.',25000);const reason=events.filter(e=>e.type==='turn/end').at(-1).data.reason;
  assert.equal(calls,5);
  const waits=events.filter(e=>e.type==='plugin:phyexp-request-recovery/scheduled');
  assert.deepEqual(waits.map(e=>e.data.delayMs),[2000,5000,2000]);
  assert.deepEqual(waits.map(e=>e.data.retry),[1,2,1]);assert.equal(reason.kind,'completed');
  assert.equal(events.filter(e=>e.type==='tool/call').length,1);
  assert.equal(reserves.length,calls);assert.deepEqual(settled.map(r=>r.id),reserves);
  const summary=gateway.persistFinal({status:'completed',turnEnd:reason});
  assert.equal(summary.failure,null);assert.equal(summary.requestRecovery.recoveredRequests,3);
  assert.equal(gateway.terminalFailure,null);await session.shutdown();
 }finally{await session.dispose();console.log('Request recovery evidence: '+dir);}
});

for(const scenario of ['exhausted','deadline','cancelled','budget','authentication','incomplete'])
 test('new baseline stops or recovers correctly: '+scenario,{timeout:155000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-baseline-'+scenario+'-'));
 const deadline=Date.now()+145000,settled=[],budget=budgetGate({deadline,softTokenLimit:300000});let calls=0;
 const gateway=new ModelGateway({model,deadline,audit:path.join(dir,'gateway.jsonl'),
  ...(scenario==='budget'?{reserve:budget.reserve}:{}),settle:async(id,result)=>{settled.push({id,...result});if(scenario==='budget')await budget.settle(id,result);},
  adapter:{async *stream(){calls++;
   if(scenario==='authentication'){yield {type:'finish',reason:{kind:'error',failure:{code:'INVALID_CREDENTIAL',message:'invalid credentials'}}};return;}
   if(scenario==='incomplete'){
    if(calls===1)return;
    yield {type:'block-start',index:0,blockType:'text'};yield {type:'block-end',index:0,block:{type:'text',text:'Recovered'}};
    yield {type:'finish',reason:{kind:'stop'}};return;
   }
   throw Error('WebSocket error');
  }}});
 const session=isolatedSession({executionRoot:'src/execution',logs:dir,gateway,
  config:{requestRecovery:policy,recoveryDeadline:scenario==='deadline'?Date.now()+1000:deadline,disableLocalTools:true,fixedModel:model,
   modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}}},
  async *handler(op){assert.equal(op,'receipt');yield {ok:true};}});
 try{
  await session.request('initialize',{...model,cwd:'/tmp/work'});
  const prompt=session.prompt('baseline-'+scenario,'Complete the fixture.',140000);prompt.catch(()=>{});
  if(scenario==='cancelled'){
   const until=Date.now()+5000;
   while(!session.messages.some(m=>m.params?.event?.type==='plugin:phyexp-request-recovery/scheduled')){
    assert.ok(Date.now()<until,'retry wait did not begin');await new Promise(r=>setTimeout(r,20));
   }
   // sdk-minimal exposes shutdown, not the full UI's session/cancel route.
   // Disposing the active agent aborts its request-error signal during the wait.
   await session.shutdown();await prompt.catch(()=>{});
   assert.equal(calls,1);assert.equal(settled.length,1);
   assert.equal(session.messages.filter(m=>m.params?.event?.type==='plugin:phyexp-request-recovery/started').length,0);
   return;
  }
  const events=await prompt,waits=events.filter(e=>e.type==='plugin:phyexp-request-recovery/scheduled');
  const reason=events.filter(e=>e.type==='turn/end').at(-1).data.reason;
  assert.equal(reason.kind,scenario==='incomplete'?'completed':'error');
  assert.equal(calls,scenario==='exhausted'?6:scenario==='incomplete'?2:1);assert.equal(settled.length,calls);
  if(scenario==='exhausted'){
   assert.deepEqual(waits.map(e=>e.data.delayMs),[2000,5000,20000,30000,60000]);
   assert.equal(events.filter(e=>e.type==='plugin:phyexp-request-recovery/stopped').at(-1).data.reason,'exhausted');
   assert.ok(settled.every(s=>!s.usage));
   assert.equal(gateway.persistFinal({status:'error',turnEnd:reason}).failure.requestId,settled.at(-1).id);
  }
  if(scenario==='budget')assert.equal(budget.snapshot().unknownReservedTokens,300000);
  if(['authentication','deadline'].includes(scenario))assert.equal(waits.length,0);
  await session.shutdown();
 }finally{await session.dispose();console.log('Baseline recovery evidence: '+dir);}
});
