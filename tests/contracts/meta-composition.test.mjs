import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import crypto from 'node:crypto';
import {MetaGateway} from '../../src/control/meta_gateway.mjs';import {isolatedSession} from '../../src/execution/host/isolation.mjs';
import {compositionEntries} from '../../packages/meta-harness/composition.mjs';
const model={provider:'openai-codex',model:'gpt-6-astra',reasoningEffort:'medium',maxTokens:8192};
function* call(name,args,id){const block={type:'tool-call',id,name,arguments:JSON.stringify(args)};yield {type:'block-start',index:0,blockType:'tool-call'};yield {type:'tool-call-delta',index:0,id,name,argumentsDelta:block.arguments};yield {type:'block-end',index:0,block};yield {type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield {type:'finish',reason:{kind:'tool-calls'}};}
function* done(){yield {type:'block-start',index:0,blockType:'text'};yield {type:'text-delta',index:0,text:'Fixture complete'};yield {type:'block-end',index:0,block:{type:'text',text:'Fixture complete'}};yield {type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield {type:'finish',reason:{kind:'stop'}};}
for(const verdict of ['approve','continue','insufficient_evidence','invalid','timeout'])test('native composition gates finish: '+verdict,{timeout:60000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-composed-meta-'));const key=crypto.randomBytes(32).toString('hex');const seen=[];let main=0,child=0;
 const manifest=JSON.parse(fs.readFileSync('packages/meta-harness/composition.json'));
 if(verdict==='timeout')manifest.plugins.find(p=>p.id==='stop-review').config.timeoutSeconds=0.2;
 const adapter={async *stream(request){
  const names=request.tools.map(t=>t.name);const system=JSON.stringify(request.messages.filter(m=>m.role==='system'));
  if(system.includes('REVIEWER_LITERAL')){
   child++;assert.ok(names.includes('structured_output'));assert.ok(names.includes('campaign_status'));assert.ok(!names.includes('campaign_finish'));assert.ok(!names.includes('workspace_write'));assert.ok(!names.includes('bash'));assert.ok(!system.includes('MAIN_LITERAL'));
   if(verdict==='timeout'){await new Promise((resolve,reject)=>{request.signal.addEventListener('abort',()=>reject(request.signal.reason),{once:true});});return;}
   if(verdict==='invalid'){yield* done();return;}
   if(child===1)yield* call('campaign_status',{input:'{}'},'query-child');
   else yield* call('structured_output',{verdict,reason:'Reviewed real fixture evidence',evidenceRefs:['e1'],missingEvidence:[],nextDirections:[]},'child-output');
  }else{
   assert.match(system,/MAIN_LITERAL/);assert.match(system,/literal \{\{unknown\}\}/);assert.ok(names.includes('campaign_finish'));assert.ok(!names.includes('structured_output'));assert.ok(!system.includes('REVIEWER_LITERAL'));
   if(main++===0)yield* call('campaign_finish',{input:JSON.stringify({condition:'exhausted',candidateId:'candidate',reason:'fixture',evidenceRefs:['e1'],attempts:[{direction:'a',finding:'b',evidenceRefs:['e1']}],remainingDirections:[],unresolved:[]})},'main-finish');else yield* done();
  }
 }};
 const gateway=new MetaGateway({mainSessionId:'composed-fixture',model,adapter,deadline:Date.now()+50000,audit:path.join(dir,'gateway.jsonl')});
 const session=isolatedSession({executionRoot:'src/execution',logs:dir,gateway,config:{disableLocalTools:true,fixedModel:model,modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},environment:{PHYEXP_META_BRIDGE_KEY:key},plugins:compositionEntries(manifest,{systemPrompt:'MAIN_LITERAL literal {{unknown}}',reviewerPrompt:'REVIEWER_LITERAL',compositionId:'fixture'})},mounts:[`type=bind,source=${path.resolve('packages/meta-harness')},target=/opt/phyexp/meta-plugin,readonly`],async *handler(op,payload){
  if(op==='receipt'){yield {ok:true};return;}
  assert.equal(op,'meta');assert.equal(payload.signature,crypto.createHmac('sha256',key).update(payload.message).digest('hex'));const body=JSON.parse(payload.message);seen.push(body);
  if(body.action==='review_request')yield {id:'review-fixture',state:'pending',request:body.input.request};
  else if(body.action==='review_result'){assert.equal(body.input.stopReason,'completed');assert.equal(body.input.result?.verdict,verdict==='invalid'?undefined:verdict);yield {id:'review-fixture',state:verdict==='approve'?'approved':verdict==='invalid'?'failed':verdict};}
  else yield {ok:true};
 }});
 try{await session.request('initialize',{...model,cwd:'/tmp/work'});const events=await session.prompt('composed-fixture','Exercise review.',40000);assert.equal(events.filter(e=>e.type==='turn/end').at(-1).data.reason.kind,'completed');
  assert.equal(child,['timeout','invalid'].includes(verdict)?1:2);assert.ok(seen.some(b=>b.action==='review_attach'));const finish=seen.find(b=>b.action==='call'&&b.input.operation==='campaign_finish');if(verdict==='approve')assert.equal(finish.input.input.reviewId,'review-fixture');else assert.equal(finish,undefined);
  if(verdict==='timeout')assert.ok(seen.some(b=>b.action==='review_failed'));
  const agents=seen.filter(b=>b.action==='register');assert.equal(agents.length,2);assert.notEqual(agents[0].input.agentId,agents[1].input.agentId);assert.ok(!agents[1].input.tools.includes('workspace_write'));await session.shutdown();
 }finally{await session.dispose();console.log('Native composition evidence: '+dir);}
});

test('disabled action plugins leave no tools or stop hooks; replacement context and fresh sessions stay scoped',{timeout:45000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-meta-variants-'));const pkg=path.join(dir,'plugins');fs.cpSync('packages/meta-harness',pkg,{recursive:true});
 fs.writeFileSync(path.join(pkg,'replacement.mjs'),`export const name='replacement';export const inject=['systemPrompt'];export function apply(ctx,config){ctx.effect(()=>ctx.systemPrompt.section({name:'replacement',order:10,text:'REPLACEMENT '+config.text,interpolate:false}));}`);
 const manifest=JSON.parse(fs.readFileSync(path.join(pkg,'composition.json')));for(const p of manifest.plugins)if(['actions','stop-review'].includes(p.id))p.enabled=false;
 manifest.plugins.find(p=>p.id==='context').module='replacement.mjs';
 const seen=[];const gateway=new MetaGateway({mainSessionId:'variant-one',model,deadline:Date.now()+35000,audit:path.join(dir,'gateway.jsonl'),adapter:{async *stream(request){
  assert.ok(request.tools.some(t=>t.name==='campaign_status'));assert.ok(!request.tools.some(t=>t.name==='campaign_finish'||t.name==='workspace_write'));
  assert.match(JSON.stringify(request.messages.filter(m=>m.role==='system')),/REPLACEMENT literal \{\{value\}\}/);
  if(request.sessionId==='variant-two')assert.ok(!JSON.stringify(request.messages).includes('PRIVATE_FIRST_SESSION'));
  yield* done();
 }}});
 const session=isolatedSession({executionRoot:'src/execution',logs:dir,gateway,config:{disableLocalTools:true,fixedModel:model,modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},environment:{PHYEXP_META_BRIDGE_KEY:'fixture-only'},plugins:compositionEntries(manifest,{systemPrompt:'literal {{value}}',reviewerPrompt:'reviewer'})},mounts:[`type=bind,source=${pkg},target=/opt/phyexp/meta-plugin,readonly`],async *handler(op,payload){if(op==='meta')seen.push(JSON.parse(payload.message));yield {ok:true};}});
 try{await session.request('initialize',{...model,cwd:'/tmp/work'});for(const id of ['variant-one','variant-two']){const events=await session.prompt(id,id==='variant-one'?'PRIVATE_FIRST_SESSION':'Second isolated session',25000);assert.equal(events.filter(e=>e.type==='turn/end').at(-1).data.reason.kind,'completed');}
 assert.equal(seen.filter(e=>e.action==='register').length,2);assert.ok(!seen.some(e=>e.action==='review_request'));await session.shutdown();}finally{await session.dispose();}
});
