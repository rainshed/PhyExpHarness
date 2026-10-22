import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {MetaHost} from '../../src/control/meta_host.mjs';
import {MetaGateway} from '../../src/control/meta_gateway.mjs';
const root=path.resolve(import.meta.dirname,'../..');
const image=process.env.PHYEXP_META_TEST_IMAGE;
const model={provider:'openai-codex',model:'gpt-6-astra',reasoningEffort:'medium',maxTokens:8192};
function* done(){yield {type:'block-start',index:0,blockType:'text'};yield {type:'text-delta',index:0,text:'done'};yield {type:'block-end',index:0,block:{type:'text',text:'done'}};yield {type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield {type:'finish',reason:{kind:'completed'}};}
function* call(name,args,id){const block={type:'tool-call',id,name,arguments:JSON.stringify(args)};yield {type:'block-start',index:0,blockType:'tool-call'};yield {type:'tool-call-delta',index:0,id,name,argumentsDelta:block.arguments};yield {type:'block-end',index:0,block};yield {type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield {type:'finish',reason:{kind:'tool-calls'}};}
test('native Meta loads six typed plugins and applicable native tools in a real isolated Runner',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-meta-native-'));const calls=[];let schemas;
 const config={id:'native-main',model,deadline:Date.now()/1000+90,workRoot:path.join(dir,'work'),sessionRoot:path.join(dir,'sessions'),pluginWorkspace:path.join(dir,'plugins'),filesRoot:path.join(dir,'files')};
 for(const p of [config.workRoot,config.sessionRoot,config.pluginWorkspace,...['evidence','materials','sdk','versions','outputs'].map(n=>path.join(config.filesRoot,n))])fs.mkdirSync(p,{recursive:true});
 const gateway=new MetaGateway({mainSessionId:config.id,model,deadline:Date.now()+90000,audit:path.join(dir,'audit'),reserve:async()=>{},settle:async()=>{},adapter:{async *stream(request){schemas=request.tools;yield*done();}}});
 const host=new MetaHost({config,root,image,logs:path.join(dir,'logs'),frozen:{id:'fixture',composition:JSON.parse(fs.readFileSync(path.join(root,'packages/meta-harness/composition-native.json'))),systemPrompt:{text:'Research {{literal}}'},reviewerPrompt:'Review'},gateway,
  modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},async api(route,body){calls.push(body);return {ok:true};}});
 try{
  const session=host.create(config.id,'meta');await session.request('initialize',{...model,cwd:'/work'});
  const events=await session.prompt(config.id,'Inspect capabilities.',45000);
  assert.equal(events.filter(e=>e.type==='turn/end').at(-1)?.data.reason.kind,'completed');
  const names=schemas.map(s=>s.name);for(const name of ['bash','read','write','campaign_finish','candidate_check','materials_read','report_get_facts','subagent','send_message','interrupt_agent','list_agents'])assert.ok(names.includes(name),name+' unavailable: '+names.join(','));
  assert.equal(schemas.find(s=>s.name==='batch_submit').parameters.properties.input,undefined);
  assert.ok(calls.some(c=>c.action==='register'));await session.shutdown();
 }finally{await host.dispose();}
});

test('long native command, human answer, research delegation and persisted session survive process replacement',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-meta-persistence-'));let phase=0;let mainCalls=0;let childCalls=0;let questionCalls=0;const calls=[];
 const config={id:'persistent-main',model,deadline:Date.now()/1000+150,workRoot:path.join(dir,'work'),sessionRoot:path.join(dir,'sessions'),pluginWorkspace:path.join(dir,'plugins'),filesRoot:path.join(dir,'files')};
 for(const p of [config.workRoot,config.sessionRoot,config.pluginWorkspace,...['evidence','materials','sdk','versions','outputs'].map(n=>path.join(config.filesRoot,n))])fs.mkdirSync(p,{recursive:true});
 const adapter={async *stream(request){
  calls.push(request);
  if(request.sessionId!==config.id){
   if(childCalls++===0)yield*call('bash',{command:'mkdir -p /work/analysis; echo RESEARCH_ARTIFACT > /work/analysis/result.txt'},'research-write');
   else yield*done();return;
  }
  const n=mainCalls++;
  if(phase===0){
   if(n===0)yield*call('bash',{command:"mkdir -p /work/analysis; export META_FIXTURE=state; printf '持久文件' > /work/analysis/kept.txt; sleep 31; echo LONG_COMMAND_DONE"},'long-command');
   else if(n===1)yield*call('bash',{command:'test "$META_FIXTURE" = state && echo SHELL_STATE_RETAINED; echo FAILED_COMMAND_TAIL; false'},'failed-command');
   else if(n===2)yield*call('ask_user_question',{questions:[{id:'scope',question:'Keep the fixture scope?'}]},'question');
   else if(n===3)yield*call('subagent',{description:'Independent fixture analysis',prompt:'Write an independent analysis file.'},'research');
   else yield*done();
  }else{
   if(n===0){assert.ok(JSON.stringify(request.messages).includes('LONG_COMMAND_DONE'),'previous turn missing from native resume');yield*call('bash',{command:"node -e \"const fs=require('fs');if(fs.readFileSync('/work/analysis/kept.txt','utf8')!=='持久文件')process.exit(1);const i=JSON.parse(fs.readFileSync('/outputs/index.json'));if(!i.items.some(r=>fs.readFileSync(r.path,'utf8').includes('LONG_COMMAND_DONE')))process.exit(2);console.log('FILES_AND_OUTPUTS_RESTORED')\""},'read-after-resume');}
   else yield*done();
  }
 }};
 const makeHost=attempt=>new MetaHost({config,root,image,logs:path.join(dir,'logs-'+attempt),frozen:{id:'fixture',composition:JSON.parse(fs.readFileSync(path.join(root,'packages/meta-harness/composition-native.json'))),systemPrompt:{text:'Research'},reviewerPrompt:'Review'},
  gateway:new MetaGateway({mainSessionId:config.id,model,deadline:Date.now()+150000,audit:path.join(dir,'audit-'+attempt),reserve:async()=>{},settle:async()=>{},adapter}),
  modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},
  async api(route,body){if(body.action==='user_question'){questionCalls++;return {state:'answered',answer:{answers:[{id:'scope',selected:[],custom:'Keep the scope'}]}};}return {ok:true};}});
 let host=makeHost(0);
 try{
  let session=host.create(config.id,'meta');await session.request('initialize',{...model,cwd:'/work'});await session.prompt(config.id,'Run persistent fixture.',80000);await session.request('session/wait',{sessionId:config.id},30000);
  assert.ok(childCalls>=2);assert.equal(questionCalls,1);
  assert.equal(host.children.size,0,'native research must not use the isolated backend');
  assert.equal(fs.readFileSync(path.join(config.workRoot,'analysis/result.txt'),'utf8').trim(),'RESEARCH_ARTIFACT');
  assert.ok(calls.some(r=>r.sessionId!==config.id));
  await session.shutdown();await host.dispose();
  phase=1;mainCalls=0;host=makeHost(1);session=host.create(config.id,'meta');await session.request('initialize',{...model,cwd:'/work'});
  await session.request('session/resume',{sessionId:config.id});const events=await session.prompt(config.id,'Verify persisted state.',45000);
  assert.equal(events.filter(e=>e.type==='turn/end').at(-1).data.reason.kind,'completed');
  const logs=[...host.runners.get(config.id).binding.outputs.entries.values()].filter(r=>r.kind==='terminal').map(r=>fs.readFileSync(path.join(config.filesRoot,'outputs','main',r.id+'.log'),'utf8'));
  for(const marker of ['LONG_COMMAND_DONE','SHELL_STATE_RETAINED','FAILED_COMMAND_TAIL','FILES_AND_OUTPUTS_RESTORED'])assert.ok(logs.some(t=>t.includes(marker)),marker);
  assert.ok(fs.existsSync(path.join(dir,'logs-1','bootstrap-receipt.json')));await session.shutdown();
 }finally{await host.dispose();}
});

test('raw PTY tail survives preview truncation; reviewer has a separate workspace and channel',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-meta-native-'));const seen=[];const counts=new Map();let approved=false;
 const config={id:'main-isolation',model,deadline:Date.now()/1000+120,workRoot:path.join(dir,'work'),sessionRoot:path.join(dir,'sessions'),pluginWorkspace:path.join(dir,'plugins'),filesRoot:path.join(dir,'files')};
 for(const p of [config.workRoot,config.sessionRoot,config.pluginWorkspace,...['evidence','materials','sdk','versions','outputs'].map(n=>path.join(config.filesRoot,n))])fs.mkdirSync(p,{recursive:true});
 fs.writeFileSync(path.join(config.workRoot,'parent-secret'),'must not be readable by children');
 const gateway=new MetaGateway({mainSessionId:config.id,model,deadline:Date.now()+120000,audit:path.join(dir,'audit'),reserve:async()=>{},settle:async()=>{},adapter:{async *stream(request){
  seen.push(request);const n=counts.get(request.sessionId)||0;counts.set(request.sessionId,n+1);
  if(request.sessionId===config.id){
   if(n===0)yield*call('bash',{command:"node -e \"process.stdout.write('长'.repeat(100000)+'TAIL_BYTES_RETAINED')\""},'long-output');
   else if(n===1)yield*call('campaign_finish',{condition:'exhausted',candidateId:'candidate',reason:'Fixture',evidenceRefs:['evidence-fixture'],attempts:[{direction:'test',finding:'test',evidenceRefs:['evidence-fixture']}],remainingDirections:[],unresolved:[],idempotencyKey:'finish'},'finish');
   else yield*done();
  }else{
   assert.ok(!request.tools.some(t=>t.name==='campaign_finish'||t.name==='subagent'));
   if(n===0)yield*call('bash',{command:'test ! -e /work/parent-secret && test ! -e /session/children && echo ROLE_ISOLATED'},'child-check');
   else yield*call('structured_output',{verdict:'approve',reason:'Isolated fixture',evidenceRefs:['evidence-fixture'],missingEvidence:[],nextDirections:[]},'review-verdict');
  }
 }}});
 const host=new MetaHost({config,root,image,logs:path.join(dir,'logs'),frozen:{id:'fixture',composition:JSON.parse(fs.readFileSync(path.join(root,'packages/meta-harness/composition-native.json'))),systemPrompt:{text:'Research'},reviewerPrompt:'Review'},gateway,
  modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},
  async api(route,body){
   if(body.action==='review_request')return {id:'review-fixture',state:'pending'};
   if(body.action==='review_result'){approved=true;return {id:'review-fixture',state:'approved'};}
   if(body.action==='review_status')return {id:'review-fixture',state:approved?'approved':'pending'};
   if(body.action==='call'&&body.input.operation==='campaign_finish'){assert.ok(approved);assert.equal(body.input.input.reviewId,'review-fixture');return {state:'closing'};}
   return {ok:true};
  }});
 try{
  const session=host.create(config.id,'meta');await session.request('initialize',{...model,cwd:'/work'});await session.prompt(config.id,'Run fixture',90000);
  assert.ok(approved,'isolated reviewer did not finish');
  const main=host.runners.get(config.id).binding;
  const logs=[...main.outputs.entries.values()].filter(r=>r.kind==='terminal').map(r=>fs.readFileSync(path.join(main.outputs.root,r.id+'.log'),'utf8'));
  assert.ok(logs.some(t=>t.includes('TAIL_BYTES_RETAINED')&&Buffer.byteLength(t)>300000));
  const child=[...host.runners.values()].find(r=>r.binding.role==='reviewer');
  const childLogs=[...child.binding.outputs.entries.values()].filter(r=>r.kind==='terminal').map(r=>fs.readFileSync(path.join(child.binding.outputs.root,r.id+'.log'),'utf8'));
  assert.ok(childLogs.some(t=>t.includes('ROLE_ISOLATED')));
  await assert.rejects(async()=>{for await(const _ of host.handle(main,'meta',{action:'review_result',input:{result:{verdict:'approve'}}})){}},/Unavailable runtime action/);
  await assert.rejects(async()=>{for await(const _ of host.handle(child.binding,'meta',{action:'call',input:{operation:'batch_submit',input:{}}})){}},/Read-only/);
  await session.shutdown();
 }finally{await host.dispose();}
});

test('all seven v4 receipts remain compact after actual native rendering and preserve path reads',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-seven-receipts-'));let step=0;const seen=[];
 const config={id:'receipt-main',model,deadline:Date.now()/1000+90,workRoot:path.join(dir,'work'),sessionRoot:path.join(dir,'sessions'),pluginWorkspace:path.join(dir,'plugins'),filesRoot:path.join(dir,'files')};
 for(const p of [config.workRoot,config.sessionRoot,config.pluginWorkspace,...['evidence','materials','sdk','versions','outputs'].map(n=>path.join(config.filesRoot,n))])fs.mkdirSync(p,{recursive:true});
 fs.writeFileSync(path.join(config.filesRoot,'materials','full.json'),JSON.stringify({text:'长'.repeat(30000)+'FULL_FILE_TAIL'}));
 const analysis={brief:'x',researchRefs:[],summary:'x',observations:[],hypotheses:[],limitations:[],decision:'x',evidenceRefs:[]};
 const inputs={campaign_status:{},candidate_list:{},evidence_list:{},sdk_read:{id:'fixture'},results_compare:{},candidate_retain:{summary:'x',alternatives:[],researchRefs:[],candidateId:'candidate',reason:'x',evidenceRefs:['e'],tradeoffs:'x',limitations:[],reconsiderWhen:'x',expectedSelectionRevision:0,idempotencyKey:'selection'},report_save:{factsId:'a'.repeat(64),analysis,expectedReportRevision:0,idempotencyKey:'report'}};
 const names=Object.keys(inputs);const adapter={async *stream(request){
  seen.push(request);
  if(step<names.length){const name=names[step++];yield*call(name,inputs[name],name);}
  else if(step++===names.length)yield*call('bash',{command:"python3 -c \"import json; s=json.load(open('/materials/full.json')); assert s['text'].endswith('FULL_FILE_TAIL'); print('FULL_FILE_TAIL_READ')\""},'read-file');
  else yield*done();
 }};
 const host=new MetaHost({config,root,image,logs:path.join(dir,'logs'),frozen:{id:'fixture',composition:JSON.parse(fs.readFileSync(path.join(root,'packages/meta-harness/composition-native.json'))),systemPrompt:{text:'Path-first fixture'},reviewerPrompt:'Review'},
 gateway:new MetaGateway({mainSessionId:config.id,model,deadline:Date.now()+90000,audit:path.join(dir,'audit'),reserve:async()=>{},settle:async()=>{},adapter}),
 modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},
 async api(route,body){return body.action==='call'?{receiptVersion:'meta-tool-receipt-v1',status:'completed',summary:'完整文件已发布',file:{ref:'fixture',path:'/materials/full.json',mediaType:'application/json',bytes:90025,sha256:'a'.repeat(64),completeness:'complete'}}:{ok:true};}});
 try{
  const session=host.create(config.id,'meta');await session.request('initialize',{...model,cwd:'/work'});await session.prompt(config.id,'Exercise path-first tools.',60000);
  const entries=[...host.runners.get(config.id).binding.outputs.entries.values()];
  assert.equal(entries.filter(e=>e.kind==='business-receipt').length,7);
  const messages=JSON.stringify(seen.at(-1).messages);assert.ok(messages.includes('FULL_FILE_TAIL_READ'));
  // Inspect provider input, not only backend objects or pre-render values.
  const results=seen.at(-1).messages.filter(m=>m.role==='tool');
  assert.equal(results.length,8);
  for(const result of results.slice(0,7)){
   const text=JSON.stringify(result);assert.ok(Buffer.byteLength(text)<4096);assert.ok(!text.includes('completeToolResult'));assert.ok(!text.includes('FULL_FILE_TAIL'));
  }
  await session.shutdown();
 }finally{await host.dispose();}
});
