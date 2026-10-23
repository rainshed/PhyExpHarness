import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fixedRequest,WireGateway} from '../../src/execution/reference/wire.mjs';
import {cliLaunch} from '../../src/execution/reference/cli.mjs';
import {captureNativeModels} from '../../packages/meta-workbench-bridge/reference-native.mjs';
import {referenceError,defaultReferencePolicy,toggleReference} from '../../packages/meta-workbench-client/reference.mjs';

test('native model capture uses effective native configuration and credential handles',async()=>{
 const config={providers:{custom:{api:'anthropic-messages',baseURL:'https://gateway.test',apiKeyEnv:'SECRET_REF',models:[{id:'pinned-model'}],compat:{}}}};
 const llm={listProviders:()=>[{id:'custom'}],listConfigurableProviders:()=>[{provider:'custom',settingsNs:'custom-provider',settingsPath:['providers','custom']}],listModels:async()=>[{id:'pinned-model',name:'Pinned'}],resolveCallConfig:async value=>({...value,maxTokens:8192}),resolveModelInfo:async()=>({id:'pinned-model',provider:'custom'})};
 const ctx={get:name=>({llm,settings:{describe:()=>[{ns:'custom-provider',value:config}]},credentials:{resolve:async ref=>({value:'host-only-secret'})}}[name]),loader:{*entries(){yield{options:{id:'custom-provider',name:'@deepseek-ai/dsh-llm-pi-ai'}};}}};
 const result=await captureNativeModels(ctx),binding=result.bindings[0];
 assert.deepEqual(binding.frozen.config,config);assert.equal(binding.frozen.call.maxTokens,8192);assert.equal(binding.credential.ref,'SECRET_REF');
 assert.equal(binding.credential.value,'host-only-secret');assert.ok(!JSON.stringify(binding.frozen).includes('host-only-secret'));
});
test('protocol gateway preserves native messages, tool schemas and reasoning signatures',()=>{
 const messages=[{role:'assistant',content:[{type:'thinking',thinking:'reason',signature:'signed'},{type:'tool_use',id:'t1',name:'bash',input:{command:'ls'}}]},{role:'user',content:[{type:'tool_result',tool_use_id:'t1',content:'result'}]}];
 const binding={protocol:'anthropic',deepseek:true,model:{model:'pinned',maxTokens:8192,reasoningEffort:'high'}};
 const body={model:'pinned',messages,tools:[{name:'bash',input_schema:{type:'object'}}],max_tokens:10};
 const result=fixedRequest(binding,{method:'POST',path:'/v1/messages?beta=true',body:JSON.stringify(body)}).body;
 assert.deepEqual(result.messages,messages);assert.deepEqual(result.tools,body.tools);assert.equal(result.max_tokens,8192);assert.deepEqual(result.thinking,{type:'enabled'});assert.equal(result.output_config.effort,'high');
 assert.throws(()=>fixedRequest(binding,{method:'POST',path:'/v1/messages',body:JSON.stringify({...body,model:'fallback'})}),/mismatch/);
 assert.throws(()=>fixedRequest(binding,{method:'POST',path:'/files',body:'{}'}),/endpoint/);
 const compact=fixedRequest({protocol:'responses',model:binding.model},{method:'POST',path:'/responses/compact',body:JSON.stringify({model:'pinned',input:[{type:'message',content:'history'}]})});
 assert.equal(compact.body.max_output_tokens,undefined);assert.deepEqual(compact.body.input,[{type:'message',content:'history'}]);
});
test('external CLI launches use fresh homes, exact auxiliary model pinning and no fallback',()=>{
 for(const harness of ['codex','claude-code']){
  const launch=cliLaunch({harness,fixedModel:{model:'pinned',reasoningEffort:'high',maxTokens:8192},mcpConnections:[{name:'qsim'}],prompt:'task'},1234);
  assert.equal(launch.env.HOME,'/work/home');assert.equal(launch.input,'task');assert.ok(!launch.args.includes('--fallback-model'));
  assert.ok(!JSON.stringify(launch).includes(process.env.HOME+'/'));
  if(harness==='claude-code')for(const key of ['ANTHROPIC_DEFAULT_HAIKU_MODEL','ANTHROPIC_DEFAULT_SONNET_MODEL','ANTHROPIC_DEFAULT_OPUS_MODEL','CLAUDE_CODE_SUBAGENT_MODEL'])assert.equal(launch.env[key],'pinned');
  else{assert.ok(launch.args.includes('--ephemeral'));assert.ok(launch.args.includes('--ignore-user-config'));assert.match(launch.args.join(' '),/request_max_retries.*0/);}
 }
});
test('host wire gateway settles complete usage, reserves unknown failures and redacts credentials',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-reference-wire-')),settled=[],admitted=[];
 try{
  const gateway=new WireGateway({binding:{protocol:'anthropic',deepseek:true,model:{model:'pinned',maxTokens:8192,reasoningEffort:'high'},baseURL:'https://gateway.test',headers:{'x-api-key':'hidden'}},deadline:Date.now()+5000,audit:path.join(dir,'audit.jsonl'),budget:{reserve:async id=>admitted.push(id),settle:async(id,result)=>settled.push(result)},fetchImpl:async(url,options)=>{
   assert.equal(url,'https://gateway.test/v1/messages');assert.equal(options.headers['x-api-key'],'hidden');
   return new Response('event: message_start\ndata: '+JSON.stringify({type:'message_start',message:{usage:{input_tokens:10,cache_read_input_tokens:2}}})+'\n\ndata: '+JSON.stringify({type:'message_delta',usage:{output_tokens:3}})+'\n\ndata: {"type":"message_stop"}\n\n',{headers:{'content-type':'text/event-stream'}});
  }});
  const chunks=[];for await(const chunk of gateway.stream({method:'POST',path:'/v1/messages',body:'{"model":"pinned","messages":[]}'}))chunks.push(chunk);
  assert.equal(chunks[0].status,200);assert.equal(admitted.length,1);assert.equal(settled[0].usage.totalTokens,15);assert.equal(settled[0].finish.kind,'completed');
  assert.ok(!fs.readFileSync(path.join(dir,'audit.jsonl'),'utf8').includes('hidden'));
  gateway.fetchImpl=async()=>{throw new Error('connection reset')};
  await assert.rejects(async()=>{for await(const _ of gateway.stream({method:'POST',path:'/v1/messages',body:'{"model":"pinned"}'})){}},/connection reset/);
  assert.equal(settled[1].usage,null);assert.equal(settled[1].finish.kind,'error');
 }finally{fs.rmSync(dir,{recursive:true,force:true})}
});
test('UI maintains independent toggles, multiselect and removes orphan pinned pairs',()=>{
 const p=defaultReferencePolicy();assert.equal(referenceError(p),'');assert.match(referenceError({...p,modelEnabled:true}),/参考模型/);
 const chosen={...p,modelEnabled:true,harnessEnabled:true,modelRefs:['m1','m2'],harnessRefs:['codex','claude-code'],selectionMode:'pinned-pairs',pairs:[{modelRef:'m1',harnessRef:'codex'}]};
 const next=toggleReference(chosen,'modelRefs','m1');assert.deepEqual(next.modelRefs,['m2']);assert.deepEqual(next.pairs,[]);assert.equal(next.harnessEnabled,true);assert.match(referenceError(next),/参考组合/);
});
