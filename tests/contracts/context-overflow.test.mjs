import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {isolatedSession} from '../../src/execution/host/isolation.mjs';

test('provider context overflow invokes native compaction and resumes through metered gateway',{timeout:30000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-overflow-'));
 const model={provider:'openai-codex',model:'gpt-6-astra',reasoningEffort:'medium',maxTokens:8192};
 const requests=[],reserves=[],settled=[];let ordinary=0;
 const gateway=new ModelGateway({model,deadline:Date.now()+25000,audit:path.join(dir,'audit.jsonl'),reserve:async id=>reserves.push(id),settle:async(id,result)=>settled.push({id,result}),
 adapter:{async *stream(request){
  requests.push(request);
  if(request.purpose!=='compaction'&&++ordinary===2){yield {type:'finish',reason:{kind:'error',failure:{code:'CONTEXT_WINDOW_EXCEEDED'}}};return;}
  const text=request.purpose==='compaction'?'Earlier records checked. Continue.':'acknowledged';
  yield {type:'block-start',index:0,blockType:'text'};yield {type:'text-delta',index:0,text};yield {type:'block-end',index:0,block:{type:'text',text}};
  yield {type:'usage',usage:{inputTokens:100,outputTokens:10,totalTokens:110}};yield {type:'finish',reason:{kind:'stop'}};
 }}});
 const session=isolatedSession({executionRoot:'src/execution',logs:dir,gateway,image:process.env.PHYEXP_COMPACTION_TEST_IMAGE||'phyexp-runner:0.2.1-rc.2',
 config:{disableLocalTools:true,fixedModel:model,modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:500000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}}},async *handler(){yield {ok:true};}});
 try{
  await session.request('initialize',{...model,cwd:'/tmp/work'});
  await session.prompt('overflow-fixture',Array.from({length:4000},(_,i)=>'record '+i+': '+(i*7919%100003)).join('\n'),10000);
  const events=await session.prompt('overflow-fixture','Continue the checks.',15000);
  assert.equal(events.filter(e=>e.type==='turn/end').at(-1)?.data.reason.kind,'completed');
  assert.ok(events.some(e=>e.type==='compaction/summary'));assert.ok(requests.some(r=>r.purpose==='compaction'));
  assert.equal(gateway.terminalFailure,null);assert.equal(gateway.diagnostics().requestRecovery.recoveredRequests,1);
  assert.deepEqual(settled.map(r=>r.id),reserves);assert.equal(reserves.length,requests.length);assert.equal(settled.filter(r=>!r.result.usage).length,1);
  await session.shutdown();
 }finally{await session.dispose();}
});
