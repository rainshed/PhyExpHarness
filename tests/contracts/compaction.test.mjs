import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {MetaGateway} from '../../src/control/meta_gateway.mjs';
import {isolatedSession} from '../../src/execution/host/isolation.mjs';

test('native automatic compaction completes through the fixed Meta gateway and is metered',{timeout:45000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-native-compaction-'));
 const model={provider:'openai-codex',model:'gpt-6-astra',reasoningEffort:'medium',maxTokens:8192};
 const requests=[],reserves=[],settlements=[];
 const gateway=new MetaGateway({mainSessionId:'compaction-fixture',model,deadline:Date.now()+40000,audit:path.join(dir,'gateway.jsonl'),
  reserve:async(id,request)=>reserves.push({id,sessionId:request.sessionId}),settle:async(id,result)=>settlements.push({id,result}),
  adapter:{async *stream(request){
   requests.push(request);assert.equal(request.reasoningEffort,model.reasoningEffort);assert.equal(request.maxTokens,model.maxTokens);
   assert.equal(request.provider,model.provider);assert.equal(request.model,model.model);assert.equal(request.sessionId,'compaction-fixture');
   const text=request.purpose==='compaction'?'The earlier fixture records were reviewed. Continue checking the remaining records.':'Fixture records acknowledged.';
   yield {type:'block-start',index:0,blockType:'text'};yield {type:'text-delta',index:0,text};
   yield {type:'block-end',index:0,block:{type:'text',text}};
   const inputTokens=Math.ceil(JSON.stringify(request.messages).length/4);
   yield {type:'usage',usage:{inputTokens,outputTokens:10,totalTokens:inputTokens+10}};yield {type:'finish',reason:{kind:'stop'}};
  }}});
 const session=isolatedSession({executionRoot:'src/execution',logs:dir,gateway,
  image:process.env.PHYEXP_COMPACTION_TEST_IMAGE||'phyexp-runner:0.2.1-rc.2',
  config:{disableLocalTools:true,fixedModel:model,modelInfo:{provider:model.provider,id:model.model,name:model.model,
   context:{contextWindow:150000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}}},async *handler(op){assert.equal(op,'receipt');yield {ok:true};}});
 try{
  await session.request('initialize',{...model,cwd:'/tmp/work'});
  const records=Array.from({length:12000},(_,i)=>`record_${i}: ${(i*7919)%100003}\n`).join('');
  await session.prompt('compaction-fixture','Review these fixture records.\n'+records,15000);
  await session.prompt('compaction-fixture','Continue with the next fixture records.\n'+records,15000);
  const events=await session.prompt('compaction-fixture','Summarize the completed checks and continue.',15000);
  const summaries=events.filter(e=>e.type==='compaction/summary');
  assert.ok(summaries.length>0,'native auto-compaction must actually run');
  assert.ok(events.filter(e=>e.type==='compaction/end').every(e=>!e.data.error));
  assert.equal(events.filter(e=>e.type==='turn/end').at(-1).data.reason.kind,'completed');
  assert.ok(requests.some(r=>r.purpose==='compaction'));
  assert.equal(requests.length,reserves.length);assert.equal(requests.length,settlements.length);
  assert.deepEqual(settlements.map(s=>s.id),reserves.map(r=>r.id));
  assert.ok(settlements.every(s=>s.result.usage.totalTokens>10));
  assert.equal(gateway.firstFailure,null);await session.shutdown();
 }finally{await session.dispose();console.log('Compaction evidence: '+dir);}
});
