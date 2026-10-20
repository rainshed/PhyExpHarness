import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createProviderCredentials} from '../../src/execution/host/provider_auth.mjs';
import {providerRuntime,ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {budgetGate} from '../../src/execution/host/budget.mjs';

const model={provider:'deepseek-official',model:'deepseek-flash',reasoningEffort:'high',maxTokens:8192};
const fakeKey='sk-phyexp-offline-test-only';
const fixtureEnv=fn=>async()=>{
 const oldKey=process.env.DEEPSEEK_API_KEY,oldAuth=process.env.PHYEXP_CODEX_AUTH_FILE;
 process.env.DEEPSEEK_API_KEY=fakeKey;process.env.PHYEXP_CODEX_AUTH_FILE='/nonexistent/offline/no-codex-auth';
 try{await fn();}finally{
  if(oldKey===undefined)delete process.env.DEEPSEEK_API_KEY;else process.env.DEEPSEEK_API_KEY=oldKey;
  if(oldAuth===undefined)delete process.env.PHYEXP_CODEX_AUTH_FILE;else process.env.PHYEXP_CODEX_AUTH_FILE=oldAuth;
 }
};
test('DeepSeek credentials need no Codex login, stay private and are removed',fixtureEnv(async()=>{
 const c=createProviderCredentials(model);
 try{
  assert.equal(fs.statSync(c.credentialFile).mode&0o777,0o600);
  assert.equal(fs.statSync(path.dirname(c.credentialFile)).mode&0o777,0o700);
  assert.deepEqual(JSON.parse(fs.readFileSync(c.credentialFile)).refs,{DEEPSEEK_API_KEY:fakeKey});
  assert.equal(c.redact('error '+fakeKey),'error [REDACTED]');
 }finally{c.dispose();}
 assert.equal(fs.existsSync(c.credentialFile),false);
 delete process.env.DEEPSEEK_API_KEY;
 assert.throws(()=>createProviderCredentials(model),/DEEPSEEK_API_KEY/);
 assert.throws(()=>createProviderCredentials({provider:'unknown'}),/Unsupported/);
}));

const sse=events=>events.map(e=>'event: '+e.type+'\ndata: '+JSON.stringify(e)+'\n\n').join('');
const start={type:'message_start',message:{id:'offline-message',type:'message',role:'assistant',model:'deepseek-flash',content:[],usage:{input_tokens:10,cache_read_input_tokens:3,cache_creation_input_tokens:2,output_tokens:0}}};
const toolEvents=[start,
 {type:'content_block_start',index:0,content_block:{type:'tool_use',id:'call-offline',name:'inspect',input:{}}},
 {type:'content_block_delta',index:0,delta:{type:'input_json_delta',partial_json:'{"value":'}},
 {type:'content_block_delta',index:0,delta:{type:'input_json_delta',partial_json:'42}'}},
 {type:'content_block_stop',index:0},
 {type:'message_delta',delta:{stop_reason:'tool_use'},usage:{output_tokens:5}},
 {type:'message_stop'}];

test('native DeepSeek streams tool JSON, replays results, settles cache usage and fixes routing',fixtureEnv(async()=>{
 const fetchBefore=globalThis.fetch;
 const c=createProviderCredentials(model),dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-ds-test-'));
 let runtime,calls=0,fixtureError;
 globalThis.fetch=async(url,init)=>{
  try { calls++;assert.equal(String(url),'https://api.deepseek.com/anthropic/v1/messages');
  assert.equal(init.headers['x-api-key'],fakeKey);
  const body=JSON.parse(init.body);assert.equal(body.model,'deepseek-flash');assert.equal(body.max_tokens,8192);
  assert.equal(body.thinking.type,'enabled');assert.equal(body.output_config.effort,'high');
  if(calls===1)return new Response(sse(toolEvents),{headers:{'content-type':'text/event-stream'}});
  assert.ok(body.messages.some(m=>m.content.some(b=>b.type==='tool_result'&&b.tool_use_id==='call-offline')));
  return new Response(sse([start,{type:'content_block_start',index:0,content_block:{type:'text',text:''}},
   {type:'content_block_delta',index:0,delta:{type:'text_delta',text:'Done'}},{type:'content_block_stop',index:0},
   {type:'message_delta',delta:{stop_reason:'end_turn'},usage:{output_tokens:2}},{type:'message_stop'}]),{headers:{'content-type':'text/event-stream'}});
  }catch(error){fixtureError=error;throw error;}
 };
 try{
  runtime=await providerRuntime({model,credentialFile:c.credentialFile});
  assert.equal(calls,0);assert.equal(runtime.info.id,'deepseek-flash');
  assert.deepEqual(runtime.info.reasoning.efforts.map(x=>x.id),['off','low','high','max']);
  const budget=budgetGate({deadline:Date.now()+10000});
  const gateway=new ModelGateway({model,adapter:runtime,deadline:Date.now()+10000,audit:path.join(dir,'audit.jsonl'),reserve:budget.reserve,settle:budget.settle});
  const messages=[{role:'user',content:[{type:'text',text:'Inspect 42'}]}];
  const request={...model,messages,tools:[{name:'inspect',description:'Offline fixture',parameters:{type:'object',properties:{value:{type:'number'}},required:['value']}}]};
  for(const field of ['provider','model','reasoningEffort','maxTokens'])await assert.rejects(async()=>{for await(const _ of gateway.stream({...request,[field]:'wrong'})){}},/mismatch/);
  const chunks=[];for await(const chunk of gateway.stream(request))chunks.push(chunk);
  assert.ok(chunks.some(c=>c.type==='block-end'),JSON.stringify(chunks));
  const tool=chunks.find(c=>c.type==='block-end').block;
  assert.equal(tool.arguments,'{"value":42}');assert.equal(chunks.at(-1).reason.kind,'tool-calls');
  assert.equal(budget.snapshot().confirmedTokens,20);
  const next={...request,messages:[...messages,{role:'assistant',content:[tool],source:{provider:model.provider,model:model.model,replayState:chunks.at(-1).replayState}},
   {role:'tool',toolCallId:tool.id,content:[{type:'text',text:'42'}]}]};
  const answer=[];for await(const chunk of gateway.stream(next))answer.push(chunk);
  if(fixtureError)throw fixtureError;
  assert.ok(answer.some(c=>c.type==='text-delta'),JSON.stringify(answer));
  assert.equal(answer.find(c=>c.type==='text-delta').text,'Done');
  assert.equal(budget.snapshot().confirmedTokens,37);assert.equal(budget.snapshot().unknownReservedTokens,0);
  assert.equal(calls,2);assert.ok(!fs.readFileSync(path.join(dir,'audit.jsonl'),'utf8').includes(fakeKey));
 }finally{globalThis.fetch=fetchBefore;await runtime?.dispose();c.dispose();fs.rmSync(dir,{recursive:true,force:true});}
}));

test('DeepSeek transport errors retain unknown reservations with no automatic retry',fixtureEnv(async()=>{
 const fetchBefore=globalThis.fetch,c=createProviderCredentials(model),dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-ds-fail-'));
 let runtime,calls=0;globalThis.fetch=async()=>{calls++;throw new Error('offline-disconnect');};
 try{
  runtime=await providerRuntime({model,credentialFile:c.credentialFile});
  const budget=budgetGate({deadline:Date.now()+5000});
  const gateway=new ModelGateway({model,adapter:runtime,deadline:Date.now()+5000,audit:path.join(dir,'audit.jsonl'),reserve:budget.reserve,settle:budget.settle});
  try{for await(const _ of gateway.stream({...model,messages:[{role:'user',content:[{type:'text',text:'Fixture'}]}]})){} }catch{}
  assert.equal(calls,1);assert.equal(budget.snapshot().unknownReservedTokens,300000);assert.ok(gateway.firstFailure);
 }finally{globalThis.fetch=fetchBefore;await runtime?.dispose();c.dispose();fs.rmSync(dir,{recursive:true,force:true});}
}));
