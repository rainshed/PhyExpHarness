import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {readLogSync} from '../../src/execution/host/log_store.mjs';
import {MetaHost} from '../../src/control/meta_host.mjs';
import {MetaGateway} from '../../src/control/meta_gateway.mjs';
const root=path.resolve(import.meta.dirname,'../..');
const model={provider:'openai-codex',model:'gpt-6-astra',reasoningEffort:'medium',maxTokens:8192};
function* done(){yield {type:'block-start',index:0,blockType:'text'};yield {type:'text-delta',index:0,text:'done'};yield {type:'block-end',index:0,block:{type:'text',text:'done'}};yield {type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield {type:'finish',reason:{kind:'completed'}};}
function* call(name,args,id){const block={type:'tool-call',id,name,arguments:JSON.stringify(args)};yield {type:'block-start',index:0,blockType:'tool-call'};yield {type:'tool-call-delta',index:0,id,name,argumentsDelta:block.arguments};yield {type:'block-end',index:0,block};yield {type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield {type:'finish',reason:{kind:'tool-calls'}};}

test('large success, denial, host failure and raw event queries stay compact through native resume',{timeout:90000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-output-contract-'));const big='证据'.repeat(900000)+'FULL_TAIL_MARKER';
 const config={id:'boundary-main',model,deadline:Date.now()/1000+85,workRoot:path.join(dir,'work'),sessionRoot:path.join(dir,'sessions'),pluginWorkspace:path.join(dir,'plugins'),filesRoot:path.join(dir,'files')};
 for(const p of [config.workRoot,config.sessionRoot,config.pluginWorkspace,...['evidence','materials','sdk','versions','outputs'].map(n=>path.join(config.filesRoot,n))])fs.mkdirSync(p,{recursive:true});
 let step=0,phase=0,receiptFile,rawSeq;const seen=[];
 const adapter={async *stream(request){
  seen.push(request);
  const results=request.messages.filter(m=>m.role==='tool');
  for(const row of results)assert.ok(Buffer.byteLength(JSON.stringify(row))<64*1024,'oversized model-facing result');
  if(phase===1){
   if(step===0){step++;yield*call('session_event_read',{seq:rawSeq,before:0,after:0},'old-event-read');}
   else if(step===1){step++;const outputs=host.runners.get(config.id).binding.outputs;const entry=[...outputs.entries.values()].find(e=>JSON.parse(readLogSync(path.join(outputs.root,e.id+'.log'))).callId==='old-event-read');
    const text=readLogSync(path.join(outputs.root,entry.id+'.log')).toString('utf8');assert.ok(text.includes('FULL_TAIL_MARKER'));const offset=Array.from(text.slice(0,text.lastIndexOf('FULL_TAIL_MARKER'))).length;
    yield*call('tool_result_read',{path:entry.path,offset,limit:100},'resume-read');
   }else yield*done();return;
  }
  if(step===0){step++;yield*call('batch_status',{batchId:'batch'},'huge-success');}
  else if(step===1){step++;yield*call('campaign_finish',{condition:'exhausted',candidateId:'candidate',reason:'Fixture',evidenceRefs:['e'],attempts:[{direction:'test',finding:'test',evidenceRefs:['e']}],remainingDirections:[],unresolved:[],idempotencyKey:'finish'},'huge-denial');}
  else if(step===2){step++;yield*call('batch_status',{batchId:'fail'},'huge-error');}
  else if(step===3){
   step++;
   // Inspect the actual persisted event and the native query tool.
   const binding=host.runners.get(config.id).binding;
   const entries=[...binding.outputs.entries.values()];
   const success=entries.map(e=>({e,value:JSON.parse(readLogSync(path.join(binding.outputs.root,e.id+'.log')))})).find(r=>r.value.callId==='huge-success');
   assert.equal(success.value.value.full,big);receiptFile=success.e;
   const sessionFile=path.join(config.sessionRoot,'sessions','--work--',config.id,'session.v4.jsonl');
   const events=fs.readFileSync(sessionFile,'utf8').trim().split('\n').map(JSON.parse);
   rawSeq=events.find(e=>e.type==='tool/result'&&e.data.callId==='huge-success')?.seq;
   // The event itself is now compact. Its underlying typed value must not have
   // leaked into persisted model history either.
   const saved=events.find(e=>e.seq===rawSeq);assert.ok(saved);assert.ok(Buffer.byteLength(JSON.stringify(saved))<64*1024);
   yield*call('session_event_read',{seq:rawSeq,before:0,after:0},'event-read');
  }else yield*done();
 }};
 const composition=JSON.parse(fs.readFileSync(path.join(root,'packages/meta-harness/composition-native.json')));
 composition.plugins.find(p=>p.id==='meta-stop-review').enabled=true;
 const makeHost=attempt=>new MetaHost({config,root,image:process.env.PHYEXP_META_TEST_IMAGE,logs:path.join(dir,'logs-'+attempt),frozen:{id:'fixture',composition,systemPrompt:{text:'Bounded results fixture'},reviewerPrompt:'Review'},
  gateway:new MetaGateway({mainSessionId:config.id,model,deadline:Date.now()+85000,audit:path.join(dir,'audit-'+attempt),reserve:async()=>{},settle:async()=>{},adapter}),
  modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},
  async api(_route,{action,input}){
   if(action==='review_request'||action==='review_status')return {id:'review',state:'continue',replayed:true,snapshot:{full:big},result:{reason:big}};
   if(action==='call'){if(input.input.batchId==='fail')throw new Error(big);return {state:'completed',full:big};}
   return {ok:true};
  }});
 let host=makeHost(0);
 try{
  let session=host.create(config.id,'meta');await session.request('initialize',{...model,cwd:'/work'});
  const events=await session.prompt(config.id,'Exercise large results.',60000);
  assert.equal(events.filter(e=>e.type==='turn/end').at(-1)?.data.reason.kind,'completed',JSON.stringify(events.at(-1)));assert.equal(step,4);
  const results=seen.at(-1).messages.filter(m=>m.role==='tool');assert.equal(results.length,4);
  assert.ok(!JSON.stringify(results).includes('FULL_TAIL_MARKER'));
  const reviews=fs.readdirSync(path.join(config.filesRoot,'materials','stop-reviews')).map(f=>JSON.parse(fs.readFileSync(path.join(config.filesRoot,'materials','stop-reviews',f))));
  assert.equal(reviews[0].snapshot.full,big);assert.equal(reviews[0].result.reason,big);
  await session.shutdown();await host.dispose();
  const history=path.join(config.sessionRoot,'sessions','--work--',config.id,'session.v4.jsonl');
  const saved=fs.readFileSync(history,'utf8').trim().split('\n').map(JSON.parse);rawSeq=saved.at(-1).seq+1;
  fs.appendFileSync(history,JSON.stringify({type:'plugin:fixture/evidence',seq:rawSeq,time:Date.now(),ignorable:true,data:{text:big}})+'\n');
  phase=1;step=0;host=makeHost(1);
  session=host.create(config.id,'meta');await session.request('initialize',{...model,cwd:'/work'});await session.request('session/resume',{sessionId:config.id});
  // Use character offsets, independent of UTF-8 byte length.
  const output=readLogSync(path.join(config.filesRoot,'outputs','main',receiptFile.id+'.log')).toString('utf8');receiptFile.bytes=Array.from(output).length;
  const resumed=await session.prompt(config.id,'Read the saved tail.',20000);
  assert.equal(resumed.filter(e=>e.type==='turn/end').at(-1)?.data.reason.kind,'completed');
  assert.ok(JSON.stringify(seen.at(-1).messages).includes('FULL_TAIL_MARKER'));
  await session.shutdown();
 }finally{await host.dispose();}
});
