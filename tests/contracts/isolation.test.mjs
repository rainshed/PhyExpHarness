import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {isolatedSession} from '../../src/execution/host/isolation.mjs';
const model={provider:'openai-codex',model:'gpt-6-sol',reasoningEffort:'medium',maxTokens:8192};
test('native dsh runs a tool loop inside credential-free network-none runner', {timeout:45000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp isolation '));const plugins=path.join(dir,'plugins');fs.mkdirSync(plugins);
 fs.writeFileSync(path.join(plugins,'probe.mjs'),`import fs from 'node:fs';import {defineTool} from '@deepseek-ai/dsh-tools';
 export const name='isolation-probe';export const inject=['tools'];export function apply(ctx){ctx.tools.register(defineTool({name:'probe',description:'Check runner isolation.',parameters:{},output:{schema:{type:'string'},render:(_,v)=>[{type:'text',text:v}]},async execute(){
 const values={credentials:fs.existsSync('/root/.codex/auth.json'),docker:fs.existsSync('/var/run/docker.sock'),host:fs.existsSync('/Users'),rootWrite:false,network:false};
 try{fs.writeFileSync('/opt/phyexp/tamper','bad');values.rootWrite=true}catch{}
 try{await fetch('https://example.com',{signal:AbortSignal.timeout(1000)});values.network=true}catch{}
 return JSON.stringify(values);}}));}`);
 let requests=0;
 const adapter={async *stream(request){requests++;if(requests===1){assert.ok(request.tools.some(t=>t.name==='probe'));
  yield {type:'block-start',index:0,blockType:'tool-call'};
  yield {type:'tool-call-delta',index:0,id:'probe-1',name:'probe',argumentsDelta:'{}'};
  yield {type:'block-end',index:0,block:{type:'tool-call',id:'probe-1',name:'probe',arguments:'{}'}};
  yield {type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield {type:'finish',reason:{kind:'tool-calls'}};
 }else{const serialized=JSON.stringify(request.messages);assert.match(serialized,/credentials/);
  for(const key of ['credentials','docker','host','rootWrite','network']) assert.ok(serialized.includes(`\\"${key}\\":false`),key+' must be denied');
  yield {type:'block-start',index:0,blockType:'text'};yield {type:'text-delta',index:0,text:'verified'};
  yield {type:'block-end',index:0,block:{type:'text',text:'verified'}};yield {type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield {type:'finish',reason:{kind:'stop'}};}}};
 const gateway=new ModelGateway({model,adapter,deadline:Date.now()+40000,audit:path.join(dir,'gateway.jsonl')});
 const session=isolatedSession({executionRoot:'src/execution',logs:dir,gateway,async *handler(op){if(op!=='receipt')throw new Error('denied');yield {ok:true};},config:{disableLocalTools:true,
  modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},
  plugins:[{id:'probe',name:'/opt/phyexp/plugins/probe.mjs'}]},mounts:[`type=bind,source=${plugins},target=/opt/phyexp/plugins,readonly`]});
 try{await session.request('initialize',{...model,cwd:'/tmp/work'});const events=await session.prompt('fixture','Run the available probe and report its result.',30000);
  assert.equal(requests,2);assert.ok(events.some(e=>e.type==='tool/result'));assert.deepEqual(await session.shutdown(),{code:0,signal:null});
 }catch(error){throw new Error(error.stack+'\n'+fs.readFileSync(path.join(dir,'stderr.log'),'utf8'));}
 finally{await session.dispose();console.log('Isolation evidence: '+dir);}
});
