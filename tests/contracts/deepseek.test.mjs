import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createProviderCredentials} from '../../src/execution/host/provider_auth.mjs';
import {providerRuntime,ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {isolatedSession} from '../../src/execution/host/isolation.mjs';

// Real native provider + real isolated dsh loop, with a synthetic Messages stream only.
for(const role of ['solver','meta'])test(`DeepSeek ${role} completes an isolated native tool loop without exposing its API key`,{timeout:45000},async()=>{
 const oldKey=process.env.DEEPSEEK_API_KEY,oldFetch=globalThis.fetch;
 process.env.DEEPSEEK_API_KEY='sk-offline-isolated-fixture';
 const model={provider:'deepseek-official',model:'deepseek-flash',reasoningEffort:role==='solver'?'off':'max',maxTokens:8192};
 const credentials=createProviderCredentials(model),dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-deepseek-'+role+'-'));
 let runtime,session,requests=0,handled=0,fetchError;
 const toolName=role==='meta'?'campaign_status':'probe';
 globalThis.fetch=async(url,init)=>{
  try{
   requests++;assert.equal(String(url),'https://api.deepseek.com/anthropic/v1/messages');
   const body=JSON.parse(init.body);assert.equal(body.model,model.model);assert.equal(body.max_tokens,8192);
   assert.equal(body.thinking.type,role==='solver'?'disabled':'enabled');
   if(role==='meta')assert.equal(body.output_config.effort,'max');
   const tools=body.tools||[];assert.ok(tools.some(t=>t.name===toolName));
   if(role==='meta')assert.ok(!tools.some(t=>t.name==='bash'));
   const start={type:'message_start',message:{id:'fixture',role:'assistant',type:'message',model:model.model,content:[],usage:{input_tokens:10,output_tokens:0}}};
   const block=requests===1?{type:'tool_use',id:'fixture-call',name:toolName,input:{}}:{type:'text',text:''};
   if(requests===2){assert.ok(JSON.stringify(body.messages).includes('offline-fixture-result'));assert.ok(!JSON.stringify(body.messages).includes(process.env.DEEPSEEK_API_KEY));}
   const events=[start,{type:'content_block_start',index:0,content_block:block},
    {type:'content_block_delta',index:0,delta:requests===1?{type:'input_json_delta',partial_json:'{}'}:{type:'text_delta',text:'Offline fixture complete'}},
    {type:'content_block_stop',index:0},{type:'message_delta',delta:{stop_reason:requests===1?'tool_use':'end_turn'},usage:{output_tokens:5}},{type:'message_stop'}];
   if(requests===1&&role==='meta')events[2].delta.partial_json=JSON.stringify({input:'{}'});
   return new Response(events.map(e=>'event: '+e.type+'\ndata: '+JSON.stringify(e)+'\n\n').join(''),{headers:{'content-type':'text/event-stream'}});
  }catch(error){fetchError=error;throw error;}
 };
 try{
  runtime=await providerRuntime({model,credentialFile:credentials.credentialFile});
  const gateway=new ModelGateway({model,adapter:runtime,deadline:Date.now()+40000,audit:path.join(dir,'gateway.jsonl')});
  const plugins=path.join(dir,'plugins');fs.mkdirSync(plugins);
  fs.writeFileSync(path.join(plugins,'probe.mjs'),`import {defineTool} from '@deepseek-ai/dsh-tools';
   export const name='probe';export const inject=['tools'];export function apply(ctx){ctx.tools.register(defineTool({name:'probe',description:'Offline isolation fixture',parameters:{},output:{schema:{type:'string'},render:(_,v)=>[{type:'text',text:v}]},execute(){if(process.env.DEEPSEEK_API_KEY)throw Error('credential leaked');return 'offline-fixture-result';}}));}`);
  session=isolatedSession({image:process.env.PHYEXP_META_TEST_IMAGE,executionRoot:'src/execution',logs:dir,gateway,
   config:{disableLocalTools:true,fixedModel:model,modelInfo:runtime.info,plugins:role==='meta'?
    [{id:'meta',name:'/opt/phyexp/meta-plugin/index.mjs',config:{systemPrompt:'Exercise the offline fixture only.'}}]:[{id:'probe',name:'/opt/phyexp/plugins/probe.mjs'}]},
   mounts:role==='meta'?[`type=bind,source=${path.resolve('packages/meta-harness')},target=/opt/phyexp/meta-plugin,readonly`]:[`type=bind,source=${plugins},target=/opt/phyexp/plugins,readonly`],
   async *handler(op,payload){if(op==='receipt'){yield {ok:true};return;}assert.equal(role,'meta');assert.equal(op,'meta');assert.equal(payload.operation,'campaign_status');handled++;yield {fixture:'offline-fixture-result'};}});
  await session.request('initialize',{...model,cwd:'/tmp/work'});
  const events=await session.prompt('fixture','Call the fixture tool, then summarize.',30000);
  if(fetchError)throw fetchError;
  assert.equal(requests,2);assert.equal(handled,role==='meta'?1:0);
  assert.equal(events.filter(e=>e.type==='turn/end').at(-1).data.reason.kind,'completed');
  assert.ok(!fs.readFileSync(path.join(dir,'gateway.jsonl'),'utf8').includes(process.env.DEEPSEEK_API_KEY));
  await session.shutdown();
 }finally{
  globalThis.fetch=oldFetch;await session?.dispose();await runtime?.dispose();credentials.dispose();
  if(oldKey===undefined)delete process.env.DEEPSEEK_API_KEY;else process.env.DEEPSEEK_API_KEY=oldKey;
  console.log('DeepSeek isolated fixture evidence: '+dir);
 }
});
