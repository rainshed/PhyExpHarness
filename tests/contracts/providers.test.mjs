import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createProviderCredentials} from '../../src/execution/host/provider_auth.mjs';
import {providerRuntime,ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {isolatedSession} from '../../src/execution/host/isolation.mjs';

for(const role of ['solver','meta'])test(`configured pi-ai ${role} uses its frozen custom route in an isolated tool loop`,{timeout:45000},async()=>{
 const fetchBefore=globalThis.fetch,keyBefore=process.env.PHYEXP_FIXTURE_KEY;
 process.env.PHYEXP_FIXTURE_KEY='sk-offline-configured-contract';
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-configured-'+role+'-'));
 const model={provider:'offline-gateway',model:'offline-model',maxTokens:1024};
 const providerConfig={adapter:'pi-ai',api:'openai-completions',baseURL:'https://offline.invalid/v1',auth:{type:'api-key',env:'PHYEXP_FIXTURE_KEY'},
  models:[{id:model.model,reasoningEfforts:false,maxTokens:1024,contextWindow:16000}]};
 const credentials=createProviderCredentials(model,{providerConfig});let runtime,session,requests=0,failure;
 const tool=role==='meta'?'campaign_status':'probe';
 globalThis.fetch=async(url,init)=>{try{
  assert.equal(String(url),'https://offline.invalid/v1/chat/completions');requests++;
  const body=JSON.parse(init.body);assert.equal(body.model,model.model);assert.equal(body.max_tokens??body.max_completion_tokens,1024);
  assert.ok(!('reasoning_effort' in body));assert.ok(!JSON.stringify(body).includes(process.env.PHYEXP_FIXTURE_KEY));
  let delta,reason;
  if(requests===1){delta={role:'assistant',tool_calls:[{index:0,id:'fixture-call',type:'function',function:{name:tool,arguments:role==='meta'?JSON.stringify({input:'{}'}):'{}'}}]};reason='tool_calls';}
  else{assert.ok(body.messages.some(m=>m.role==='tool'&&m.content.includes('offline-fixture-result')));delta={role:'assistant',content:'Offline complete'};reason='stop';}
  const events=[{id:'offline',object:'chat.completion.chunk',model:model.model,choices:[{index:0,delta,finish_reason:null}]},
   {id:'offline',object:'chat.completion.chunk',model:model.model,choices:[{index:0,delta:{},finish_reason:reason}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12}}];
  return new Response(events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join(''),{headers:{'content-type':'text/event-stream'}});
 }catch(error){failure=error;throw error;}};
 try{
  runtime=await providerRuntime({model,providerConfig,credentialFile:credentials.credentialFile});
  const gateway=new ModelGateway({model,adapter:runtime,deadline:Date.now()+40000,audit:path.join(dir,'gateway.jsonl')});
  const plugins=path.join(dir,'plugins');fs.mkdirSync(plugins);
  fs.writeFileSync(path.join(plugins,'probe.mjs'),`import {defineTool} from '@deepseek-ai/dsh-tools';export const name='probe';export const inject=['tools'];export function apply(ctx){ctx.tools.register(defineTool({name:'probe',description:'Fixture',parameters:{},output:{schema:{type:'string'},render:(_,v)=>[{type:'text',text:v}]},execute(){if(process.env.PHYEXP_FIXTURE_KEY)throw Error('secret leaked');return 'offline-fixture-result';}}));}`);
  session=isolatedSession({image:process.env.PHYEXP_META_TEST_IMAGE,executionRoot:'src/execution',logs:dir,gateway,
   config:{disableLocalTools:true,fixedModel:model,modelInfo:runtime.info,plugins:role==='meta'?[{id:'meta',name:'/opt/phyexp/meta-plugin/index.mjs',config:{systemPrompt:'Offline fixture'}}]:[{id:'probe',name:'/opt/phyexp/plugins/probe.mjs'}]},
   mounts:role==='meta'?[`type=bind,source=${path.resolve('packages/meta-harness')},target=/opt/phyexp/meta-plugin,readonly`]:[`type=bind,source=${plugins},target=/opt/phyexp/plugins,readonly`],
   async *handler(op,payload){if(op==='receipt'){yield {ok:true};return;}assert.equal(op,'meta');assert.equal(payload.operation,'campaign_status');yield {fixture:'offline-fixture-result'};}});
  await session.request('initialize',{...model,cwd:'/tmp/work'});
  const events=await session.prompt('fixture','Exercise the fixture tool.',30000);
  if(failure)throw failure;
  assert.equal(requests,2);assert.equal(events.filter(e=>e.type==='turn/end').at(-1).data.reason.kind,'completed');
  await session.shutdown();
 }finally{globalThis.fetch=fetchBefore;await session?.dispose();await runtime?.dispose();credentials.dispose();if(keyBefore===undefined)delete process.env.PHYEXP_FIXTURE_KEY;else process.env.PHYEXP_FIXTURE_KEY=keyBefore;console.log('Configured provider evidence: '+dir);}
});
