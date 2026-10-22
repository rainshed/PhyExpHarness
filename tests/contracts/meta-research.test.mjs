import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {MetaHost} from '../../src/control/meta_host.mjs';
import {MetaGateway} from '../../src/control/meta_gateway.mjs';
import {localSessionFactory} from './helpers/meta-local-session.mjs';

const root=path.resolve(import.meta.dirname,'../..');
const model={provider:'openai-codex',model:'gpt-6-astra',reasoningEffort:'medium',maxTokens:8192};
function* done(){yield {type:'block-start',index:0,blockType:'text'};yield {type:'text-delta',index:0,text:'Fixture turn complete'};yield {type:'block-end',index:0,block:{type:'text',text:'Fixture turn complete'}};yield {type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield {type:'finish',reason:{kind:'completed'}};}
function* call(name,args,id){const block={type:'tool-call',id,name,arguments:JSON.stringify(args)};yield {type:'block-start',index:0,blockType:'tool-call'};yield {type:'tool-call-delta',index:0,id,name,argumentsDelta:block.arguments};yield {type:'block-end',index:0,block};yield {type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield {type:'finish',reason:{kind:'tool-calls'}};}
async function until(check){const end=Date.now()+30000;while(!check()){if(Date.now()>end)throw new Error('Fixture checkpoint not reached');await delay(25);}}

for(const explicitCwd of [true,false])test(`native research (${explicitCwd?'explicit':'inherited'} cwd) accepts live/idle follow-ups and cold-resumes after Runner replacement`,{timeout:180000},async()=>{
 const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-native-research-')));
 const config={id:'research-main',model,deadline:Date.now()/1000+1800,workRoot:path.join(dir,'work'),sessionRoot:path.join(dir,'sessions'),pluginWorkspace:path.join(dir,'plugins'),filesRoot:path.join(dir,'files')};
 const childWork=path.join(config.workRoot,'agents','analysis');
 const local=process.env.PHYEXP_META_LOCAL_TEST==='1'?await localSessionFactory():null;
 const runnerWork=local?config.workRoot:'/work';const runnerChild=runnerWork+'/agents/analysis';
 for(const folder of [config.workRoot,childWork,config.sessionRoot,config.pluginWorkspace,...['evidence','materials','sdk','versions'].map(n=>path.join(config.filesRoot,n))])fs.mkdirSync(folder,{recursive:true});
 fs.writeFileSync(path.join(config.pluginWorkspace,'draft.txt'),'SHARED_DRAFT');
 if(local)fs.symlinkSync(config.pluginWorkspace,path.join(config.workRoot,'plugins'),'dir');
 const frozen={id:'fixture',composition:JSON.parse(fs.readFileSync(path.join(root,'packages/meta-harness/composition-native.json'))),systemPrompt:{text:'Research fixture'},reviewerPrompt:'Independent review'};
 let phase='initial',childId;const counts=new Map(),requests=[],registrations=[],accounted=[];
 const adapter={async *stream(request){
  requests.push(request);assert.equal(request.maxTokens,model.maxTokens,'fixed output cap must survive native activation/resume');const key=phase+':'+request.sessionId,n=counts.get(key)||0;counts.set(key,n+1);
  if(request.sessionId===config.id){
   if(phase==='initial'&&n===0)yield*call('subagent',{...(explicitCwd?{cwd:runnerChild}:{}),description:'Analyze shared draft',prompt:'Record FIRST_RESEARCH_CONTEXT and report to your parent.'},'spawn');
   else if(phase==='followup'&&n===0)yield*call('send_message',{agent_id:childId,message:'FOLLOWUP_RESEARCH_CONTEXT: check your earlier findings.'},'followup');
   else if(phase==='steer'&&n===0)yield*call('send_message',{agent_id:childId,message:'Start work while the parent prepares another instruction.'},'begin-active-work');
   else if(phase==='steer'&&n===1){await until(()=>fs.existsSync(path.join(childWork,'steer-checkpoint.txt')));yield*call('send_message',{agent_id:childId,message:'ACTIVE_FOLLOWUP_CONTEXT: include this instruction when you report.'},'steer-active-work');}
   else if(phase==='cancel'&&n===0)yield*call('send_message',{agent_id:childId,message:'Start work that the parent will interrupt.'},'begin-cancel-work');
   else if(phase==='cancel'&&n===1){await until(()=>fs.existsSync(path.join(childWork,'cancel-checkpoint.txt')));yield*call('interrupt_agent',{agent_id:childId},'cancel-active-work');}
   else if(phase==='interrupt'&&n===0)yield*call('send_message',{agent_id:childId,message:'INTERRUPTED_RESEARCH_CONTEXT: create a durable checkpoint and start work.'},'begin-long-work');
   else if(phase==='resume'&&n===0)yield*call('list_agents',{},'discover-restored-child');
   else if(phase==='resume'&&n===1){assert.ok(JSON.stringify(request.messages).includes(childId));yield*call('send_message',{agent_id:childId,message:'Resume the interrupted task. Check history and files before doing more work.'},'resume-child');}
   else yield*done();return;
  }
  if(childId)assert.equal(request.sessionId,childId,'continuation must retain child identity');else childId=request.sessionId;
  const tools=request.tools.map(t=>t.name);assert.ok(tools.includes('send_message'));assert.ok(!tools.includes('batch_submit'));assert.ok(!tools.includes('campaign_finish'));assert.ok(!tools.includes('subagent'));
  if(n===0){
   const history=JSON.stringify(request.messages);
   if(phase!=='initial')assert.ok(history.includes('FIRST_RESEARCH_CONTEXT'),'child history lost');
   if(phase==='resume'){
    assert.ok(history.includes('FOLLOWUP_RESEARCH_CONTEXT'));assert.ok(history.includes('ACTIVE_FOLLOWUP_CONTEXT'));assert.ok(history.includes('INTERRUPTED_RESEARCH_CONTEXT'));
    yield*call('bash',{command:`test "$PWD" = '${runnerChild}' && test "$(cat checkpoint.txt)" = INTERRUPTED_CHECKPOINT && test -f first.txt && test -f followup.txt && echo COLD_RESUME_OK > resumed.txt`},'resume-files');
   }else if(phase==='steer')yield*call('bash',{command:'echo STEER_CHECKPOINT > steer-checkpoint.txt; sleep 2; echo ACTIVE_WORK_FINISHED'},'steer-command');
   else if(phase==='cancel')yield*call('bash',{command:'echo CANCEL_CHECKPOINT > cancel-checkpoint.txt; sleep 60 && echo UNEXPECTED_END > finished-cancel-command.txt'},'cancel-command');
   else if(phase==='interrupt')yield*call('bash',{command:'echo INTERRUPTED_CHECKPOINT > checkpoint.txt; sleep 60 && echo UNEXPECTED_END > finished-long-command.txt'},'interrupted-command');
   else yield*call('bash',{command:`test "$PWD" = '${runnerChild}' && test "$(cat '${runnerWork}/plugins/draft.txt')" = SHARED_DRAFT && echo ${phase==='initial'?'FIRST_RESEARCH_CONTEXT > first.txt':'FOLLOWUP_RESEARCH_CONTEXT > followup.txt'}`},phase+'-files');
  }else if(n===1){
   if(phase==='steer')assert.ok(JSON.stringify(request.messages).includes('ACTIVE_FOLLOWUP_CONTEXT'),'running child lost the live follow-up');
   yield*call('send_message',{agent_id:config.id,message:'Research result available in /work/agents/analysis; phase '+phase},phase+'-report');
  }
  else yield*done();
 }};
 const makeHost=attempt=>new MetaHost({config,root,...(local?{sessionFactory:local.factory}:{}),image:process.env.PHYEXP_META_TEST_IMAGE,logs:path.join(dir,'logs-'+attempt),frozen,
  gateway:new MetaGateway({mainSessionId:config.id,model,deadline:config.deadline*1000,audit:path.join(dir,'audit-'+attempt),reserve:async(_id,request)=>accounted.push(request.sessionId),settle:async()=>{},adapter}),
  modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},
  async api(_route,body){if(body.action==='register')registrations.push(body.input);return {ok:true};}});
 let host=makeHost(0),session;
 try{
  session=host.create(config.id,'meta');await session.request('initialize',{...model,cwd:explicitCwd?runnerWork:runnerChild});
  await session.prompt(config.id,'Start the research fixture.',60000);await session.request('session/wait',{sessionId:config.id},60000);
  assert.ok(fs.existsSync(path.join(childWork,'first.txt')));assert.equal(host.children.size,0);
  phase='followup';await session.prompt(config.id,'Follow up with the same analyst.',60000);await session.request('session/wait',{sessionId:config.id},60000);
  assert.ok(fs.existsSync(path.join(childWork,'followup.txt')));
  phase='steer';await session.prompt(config.id,'Send another instruction while the analyst is working.',60000);await session.request('session/wait',{sessionId:config.id},60000);
  phase='cancel';await session.prompt(config.id,'Interrupt active research through the native tool.',60000);await session.request('session/wait',{sessionId:config.id},60000);
  assert.ok(!fs.existsSync(path.join(childWork,'finished-cancel-command.txt')));
  phase='interrupt';const pending=session.prompt(config.id,'Start work to interrupt.',60000);pending.catch(()=>{});
  await until(()=>fs.existsSync(path.join(childWork,'checkpoint.txt')));
  await host.dispose();await pending.catch(()=>{});
  assert.ok(!fs.existsSync(path.join(childWork,'finished-long-command.txt')));
  phase='resume';host=makeHost(1);session=host.create(config.id,'meta');await session.request('initialize',{...model,cwd:explicitCwd?runnerWork:runnerChild});
  await session.request('session/resume',{sessionId:config.id});
  await session.prompt(config.id,'Discover and continue the previous research task.',60000);await session.request('session/wait',{sessionId:config.id},60000);
  assert.equal(fs.readFileSync(path.join(childWork,'resumed.txt'),'utf8').trim(),'COLD_RESUME_OK');
  assert.equal(host.children.size,0);assert.ok(accounted.includes(childId));assert.ok(accounted.includes(config.id));
  assert.ok(registrations.filter(r=>r.agentId===childId).length>=2,'cold resume must register child for accounting');
  assert.ok(registrations.filter(r=>r.agentId===childId).every(r=>r.preset==='phyexp-researcher'&&r.isolationScope==='activity-research'));
  await session.shutdown();
 }finally{await host.dispose();await local?.close();}
});
