import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createProviderCredentials} from '../../src/execution/host/provider_auth.mjs';
import {providerRuntime,ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {providerRoute} from '../../src/execution/host/providers.mjs';
import {budgetGate} from '../../src/execution/host/budget.mjs';
const model={provider:'fixture-gateway',model:'fixture-model',maxTokens:1024};
const route=api=>({adapter:'pi-ai',api,baseURL:'https://fixture.invalid/v1',auth:{type:'api-key',env:'PHYEXP_FIXTURE_KEY'},
 models:[{id:model.model,name:'Fixture',reasoningEfforts:false,contextWindow:16000,maxTokens:1024}]});
const encode=events=>events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join('');
const responseEvents=[{type:'response.created',response:{id:'r-fixture',model:'fixture-model',status:'in_progress',output:[]}},
 {type:'response.output_item.added',output_index:0,item:{type:'message',id:'msg-fixture',role:'assistant',content:[],status:'in_progress'}},
 {type:'response.content_part.added',output_index:0,content_index:0,item_id:'msg-fixture',part:{type:'output_text',text:'',annotations:[]}},
 {type:'response.output_text.delta',output_index:0,content_index:0,item_id:'msg-fixture',delta:'fixture answer'},
 {type:'response.output_item.done',output_index:0,item:{type:'message',id:'msg-fixture',role:'assistant',status:'completed',content:[{type:'output_text',text:'fixture answer',annotations:[]}]}},
 {type:'response.completed',response:{id:'r-fixture',model:'fixture-model',status:'completed',output:[],usage:{input_tokens:10,output_tokens:2,total_tokens:12,input_tokens_details:{cached_tokens:0},output_tokens_details:{reasoning_tokens:0}}}}];
const completions=[{id:'c-fixture',object:'chat.completion.chunk',created:1,model:model.model,choices:[{index:0,delta:{role:'assistant',content:'fixture answer'},finish_reason:null}]},
 {id:'c-fixture',object:'chat.completion.chunk',created:1,model:model.model,choices:[{index:0,delta:{},finish_reason:'stop'}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12}}];
const messages=[{type:'message_start',message:{id:'msg-fixture',type:'message',role:'assistant',model:model.model,content:[],usage:{input_tokens:10,output_tokens:0}}},
 {type:'content_block_start',index:0,content_block:{type:'text',text:''}},{type:'content_block_delta',index:0,delta:{type:'text_delta',text:'fixture answer'}},
 {type:'content_block_stop',index:0},{type:'message_delta',delta:{stop_reason:'end_turn'},usage:{output_tokens:2}},{type:'message_stop'}];
for(const api of ['openai-completions','openai-responses','anthropic-messages'])test('configured '+api+' uses native pi-ai, named credentials and authoritative usage',async()=>{
 const beforeFetch=globalThis.fetch,oldKey=process.env.PHYEXP_FIXTURE_KEY;
 process.env.PHYEXP_FIXTURE_KEY='sk-offline-provider-fixture';
 const providerConfig=route(api);if(api==='anthropic-messages')providerConfig.baseURL='https://fixture.invalid';
 const credentials=createProviderCredentials(model,{providerConfig});
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-provider-config-'));let runtime,calls=0,error;
 globalThis.fetch=async(url,init)=>{try{
  calls++;const suffix=api==='openai-completions'?'chat/completions':api==='openai-responses'?'responses':'messages';
  assert.equal(String(url),'https://fixture.invalid/v1/'+suffix+(api==='anthropic-messages'?'?beta=true':''));
  const headers=new Headers(init.headers);
  assert.equal(headers.get(api==='anthropic-messages'?'x-api-key':'authorization'),api==='anthropic-messages'?process.env.PHYEXP_FIXTURE_KEY:'Bearer '+process.env.PHYEXP_FIXTURE_KEY);
  const body=JSON.parse(init.body);assert.equal(body.model,model.model);assert.ok(!JSON.stringify(body).includes('reasoning_effort'));
  const events=api==='openai-completions'?completions:api==='openai-responses'?responseEvents:messages;
  return new Response(api==='anthropic-messages'?events.map(e=>'event: '+e.type+'\ndata: '+JSON.stringify(e)+'\n\n').join(''):encode(events),{headers:{'content-type':'text/event-stream'}});
 }catch(e){error=e;throw e;}};
 try{
  runtime=await providerRuntime({model,providerConfig,credentialFile:credentials.credentialFile});assert.equal(calls,0);
  const budget=budgetGate({deadline:Date.now()+5000});
  const gateway=new ModelGateway({model,adapter:runtime,deadline:Date.now()+5000,audit:path.join(dir,'audit.jsonl'),reserve:budget.reserve,settle:budget.settle});
  const chunks=[];for await(const c of gateway.stream({...model,messages:[{role:'user',content:[{type:'text',text:'Offline fixture'}]}]}))chunks.push(c);
  if(error)throw error;
  assert.equal(chunks.filter(c=>c.type==='text-delta').map(c=>c.text).join(''),'fixture answer',JSON.stringify(chunks));
  assert.equal(calls,1);assert.equal(chunks.at(-1).reason.kind,'stop');assert.equal(budget.snapshot().confirmedTokens,12);
  assert.equal(budget.snapshot().unknownReservedTokens,0);
 }finally{globalThis.fetch=beforeFetch;await runtime?.dispose();credentials.dispose();fs.rmSync(dir,{recursive:true,force:true});if(oldKey===undefined)delete process.env.PHYEXP_FIXTURE_KEY;else process.env.PHYEXP_FIXTURE_KEY=oldKey;}
});

test('Codex subscription bridge retains OAuth record and calls the original endpoint without an API key',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-codex-regression-'));
 const beforeFetch=globalThis.fetch,beforeFile=process.env.PHYEXP_CODEX_AUTH_FILE;
 const payload={exp:Math.floor(Date.now()/1000)+7200,'https://api.openai.com/auth':{chatgpt_account_id:'offline-account'}};
 const token='fixture.'+Buffer.from(JSON.stringify(payload)).toString('base64url')+'.signature';
 const authFile=path.join(dir,'auth.json');fs.writeFileSync(authFile,JSON.stringify({auth_mode:'chatgpt',tokens:{access_token:token,refresh_token:'must-not-be-copied'}}));
 process.env.PHYEXP_CODEX_AUTH_FILE=authFile;
 let credentials,runtime,calls=0,error;
 const subscription={provider:'openai-codex',model:'gpt-6-sol',reasoningEffort:'medium',maxTokens:8192};
 const providerConfig={...providerRoute(subscription),transport:'sse'};
 globalThis.fetch=async(url,init)=>{try{
  calls++;assert.equal(String(url),'https://chatgpt.com/backend-api/codex/responses');
  const headers=new Headers(init.headers);assert.equal(headers.get('authorization'),'Bearer '+token);assert.equal(headers.get('chatgpt-account-id'),'offline-account');
  return new Response(encode(responseEvents),{headers:{'content-type':'text/event-stream'}});
 }catch(e){error=e;throw e;}};
 try{
  credentials=createProviderCredentials(subscription,{providerConfig});
  const record=JSON.parse(fs.readFileSync(credentials.credentialFile));
  assert.equal(record.records['llm-pi-ai/openai-codex'].payload.access,token);
  assert.equal(record.records['llm-pi-ai/openai-codex'].payload.refresh,'');assert.deepEqual(record.refs,{});
  runtime=await providerRuntime({model:subscription,providerConfig,credentialFile:credentials.credentialFile});
  const chunks=[];for await(const c of runtime.stream({...subscription,messages:[{role:'user',content:[{type:'text',text:'Offline subscription fixture'}]}]}))chunks.push(c);
  if(error)throw error;
  assert.equal(calls,1);assert.equal(chunks.at(-1).reason.kind,'stop',JSON.stringify(chunks));
  assert.equal(chunks.find(c=>c.type==='usage').usage.totalTokens,12);
  assert.ok(!fs.readFileSync(credentials.credentialFile,'utf8').includes('must-not-be-copied'));
  const original=JSON.parse(fs.readFileSync(authFile));assert.equal(original.tokens.refresh_token,'must-not-be-copied');
 }finally{globalThis.fetch=beforeFetch;await runtime?.dispose();credentials?.dispose();if(beforeFile===undefined)delete process.env.PHYEXP_CODEX_AUTH_FILE;else process.env.PHYEXP_CODEX_AUTH_FILE=beforeFile;fs.rmSync(dir,{recursive:true,force:true});}
});

test('route validation refuses subscription redirection, embedded secrets and invalid protocols',()=>{
 const gpt={provider:'openai-codex',model:'gpt-6-sol',reasoningEffort:'medium'};
 assert.throws(()=>providerRoute(gpt,{...providerRoute(gpt),baseURL:'https://fixture.invalid'}),/subscription/);
 for(const bad of [{...route('unknown')},{...route('openai-completions'),apiKey:'secret'},
  {...route('openai-completions'),baseURL:'https://secret:password@fixture.invalid'},
  {...route('openai-completions'),auth:{type:'codex'}}])assert.throws(()=>providerRoute(model,bad));
});

test('configured reasoning mapping and streamed tool arguments survive a pi-ai round trip',async()=>{
 const oldFetch=globalThis.fetch,oldKey=process.env.PHYEXP_FIXTURE_KEY;
 process.env.PHYEXP_FIXTURE_KEY='sk-offline-tool-fixture';
 const selected={...model,reasoningEffort:'max'};
 const providerConfig=route('openai-completions');
 providerConfig.models[0].reasoningEfforts={off:null,max:'high'};providerConfig.models[0].defaultReasoningEffort='max';
 providerConfig.compat={supportsReasoningEffort:true,thinkingFormat:'openai'};
 const credentials=createProviderCredentials(selected,{providerConfig});let runtime,n=0,failure;
 globalThis.fetch=async(_url,init)=>{try{
  n++;const body=JSON.parse(init.body);assert.equal(body.reasoning_effort,'high');
  if(n===2){assert.ok(body.messages.some(m=>m.role==='tool'&&m.tool_call_id==='call-fixture'));return new Response(encode(completions),{headers:{'content-type':'text/event-stream'}});}
  const events=[{id:'fixture',object:'chat.completion.chunk',model:model.model,choices:[{index:0,delta:{role:'assistant',tool_calls:[{index:0,id:'call-fixture',type:'function',function:{name:'echo',arguments:'{"value":'}}]},finish_reason:null}]},
   {id:'fixture',object:'chat.completion.chunk',model:model.model,choices:[{index:0,delta:{tool_calls:[{index:0,function:{arguments:'42}'}}]},finish_reason:null}]},
   {id:'fixture',object:'chat.completion.chunk',model:model.model,choices:[{index:0,delta:{},finish_reason:'tool_calls'}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12}}];
  return new Response(encode(events),{headers:{'content-type':'text/event-stream'}});
 }catch(e){failure=e;throw e;}};
 try{
  runtime=await providerRuntime({model:selected,providerConfig,credentialFile:credentials.credentialFile});
  const request={...selected,messages:[{role:'user',content:[{type:'text',text:'Echo fixture'}]}],tools:[{name:'echo',description:'Fixture',parameters:{type:'object',properties:{value:{type:'number'}}}}]};
  const first=[];for await(const chunk of runtime.stream(request))first.push(chunk);
  if(failure)throw failure;
  const tool=first.find(c=>c.type==='block-end')?.block;assert.equal(tool?.arguments,'{"value":42}',JSON.stringify(first));
  const next={...request,messages:[...request.messages,{role:'assistant',content:[tool],source:{provider:selected.provider,model:selected.model,replayState:first.at(-1).replayState}},
   {role:'tool',toolCallId:tool.id,content:[{type:'text',text:'42'}]}]};
  const second=[];for await(const chunk of runtime.stream(next))second.push(chunk);
  if(failure)throw failure;assert.equal(n,2);assert.equal(second.at(-1).reason.kind,'stop',JSON.stringify(second));
 }finally{globalThis.fetch=oldFetch;await runtime?.dispose();credentials.dispose();if(oldKey===undefined)delete process.env.PHYEXP_FIXTURE_KEY;else process.env.PHYEXP_FIXTURE_KEY=oldKey;}
});
