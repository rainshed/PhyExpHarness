import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {isolatedSession} from '../../src/execution/host/isolation.mjs';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
const imageFile=process.env.PHYEXP_REFERENCE_IMAGES||'.runtime/reference-acceptance/images.json';
const receipts=fs.existsSync(imageFile)?JSON.parse(fs.readFileSync(imageFile)):{};
const missing='Optional reference images are not prepared; run npm run test:references';
const model={provider:'fixture',model:'fixture-model',maxTokens:8192};
const dir=name=>fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-reference-'+name+'-'));
const evidence=(root,error)=>new Error(error.stack+'\nEvidence: '+root+'\n'+fs.readFileSync(path.join(root,'stderr.log'),'utf8'));
test('DeepSeek standard is the complete base + SDK profile, with task tool loop',{timeout:90000,skip:!receipts['dsh-standard']?.image&&missing},async()=>{
 const root=dir('standard');let calls=0,tools=0,bootstrap;
 const gateway=new ModelGateway({model,deadline:Date.now()+75000,audit:path.join(root,'gateway.jsonl'),adapter:{async *stream(request){
  calls++;
  if(calls===1){
   assert.ok(request.tools.some(t=>t.name==='task_bash'));assert.ok(request.tools.some(t=>t.name==='read'));assert.ok(request.tools.some(t=>t.name==='write'));
   yield{type:'block-start',index:0,blockType:'tool-call'};yield{type:'tool-call-delta',index:0,id:'tool1',name:'task_bash',argumentsDelta:'{"command":"printf reference-ok"}'};
   yield{type:'block-end',index:0,block:{type:'tool-call',id:'tool1',name:'task_bash',arguments:'{"command":"printf reference-ok"}'}};
   yield{type:'usage',usage:{inputTokens:10,outputTokens:10,totalTokens:20}};yield{type:'finish',reason:{kind:'tool-calls'}};
  }else{assert.match(JSON.stringify(request.messages),/reference-ok/);yield{type:'block-start',index:0,blockType:'text'};yield{type:'text-delta',index:0,text:'Done'};yield{type:'block-end',index:0,block:{type:'text',text:'Done'}};yield{type:'usage',usage:{inputTokens:10,outputTokens:5,totalTokens:15}};yield{type:'finish',reason:{kind:'stop'}};}
 }}});
 const session=isolatedSession({executionRoot:'src/execution',logs:root,image:receipts['dsh-standard'].image,gateway,
  config:{standardReference:true,disableLocalTools:false,fixedModel:model,modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:128000},defaultMaxTokens:8192},mcpConnections:[],environment:{PHYEXP_TASK_TOOL_NAME:'task_bash'},plugins:[{id:'container-tools',name:'/opt/phyexp/src/execution/adapters/quantum_harbor/container_tool.mjs'}]},
  async *handler(op,payload){if(op==='receipt'){if(payload.kind==='bootstrap')bootstrap=payload;yield{ok:true};}else if(op==='tool'){tools++;assert.equal(payload.command,'printf reference-ok');yield{stdout:'reference-ok',stderr:'',returnCode:0};}else throw new Error('denied');}});
 try{
  await session.request('initialize',{...model,cwd:'/tmp/work'},60000);const events=await session.prompt('standard-fixture','Use task_bash once.',30000);
  assert.equal(tools,1);assert.equal(calls,2);assert.equal(events.filter(e=>e.type==='turn/end').at(-1).data.reason.kind,'completed');
  assert.ok(bootstrap.entries.some(e=>e.id==='sdk-app-startup'));assert.ok(bootstrap.entries.some(e=>e.id==='tool-fs'));assert.ok(bootstrap.entries.some(e=>e.id==='tool-bash'));
  assert.deepEqual(await session.shutdown(),{code:0,signal:null});
 }catch(error){throw evidence(root,error)}finally{await session.dispose();console.log('Reference standard evidence: '+root)}
});
for(const harness of ['codex','claude-code'])test(harness+' real CLI runs fresh MCP task loop through isolated host wire bridge',{timeout:90000,skip:!receipts[harness]?.image&&missing},async()=>{
 const root=dir(harness);let calls=0,tools=0;const requests=[];
 const gateway={abort(){}};
 const session=isolatedSession({executionRoot:'src/execution',logs:root,image:receipts[harness].image,gateway,entry:'/opt/phyexp/src/execution/reference/isolated.mjs',
  config:{harness,fixedModel:model,mcpConnections:[],prompt:'Use the task MCP task_bash tool once to run printf reference-ok. Then say done.'},
  async *handler(op,payload){
   if(op==='tool'){tools++;assert.equal(payload.command,'printf reference-ok');yield{stdout:'reference-ok',stderr:'',returnCode:0};return;}
   assert.equal(op,'wire');const body=JSON.parse(payload.body);requests.push(body);fs.writeFileSync(path.join(root,'fixture-requests.json'),JSON.stringify(requests,null,2));assert.equal(body.model,model.model);
   if(payload.path.includes('count_tokens')){yield{status:200,headers:{'content-type':'application/json'}};yield{bytes:Buffer.from('{"input_tokens":100}').toString('base64')};return;}
   calls++;yield{status:200,headers:{'content-type':'text/event-stream'}};
   const found=(body.tools||[]).flatMap(t=>t.type==='namespace'?t.tools.map(tool=>({...tool,namespace:t.name})):[t]).find(t=>t.name?.includes('task_bash'));
   let events=[];
   if(harness==='claude-code'){
    const content=calls===1?{type:'tool_use',id:'tool1',name:found?.name,input:{}}:{type:'text',text:''};
    assert.ok(found?.name,'task MCP schema must be attached');
    events=[{type:'message_start',message:{id:'message'+calls,type:'message',role:'assistant',model:body.model,content:[],stop_reason:null,stop_sequence:null,usage:{input_tokens:20,output_tokens:0}}},
     {type:'content_block_start',index:0,content_block:content},
     {type:'content_block_delta',index:0,delta:calls===1?{type:'input_json_delta',partial_json:'{"command":"printf reference-ok"}'}:{type:'text_delta',text:'done'}},
     {type:'content_block_stop',index:0},{type:'message_delta',delta:{stop_reason:calls===1?'tool_use':'end_turn',stop_sequence:null},usage:{output_tokens:10}},{type:'message_stop'}];
   }else{
    assert.ok(found?.name,'task MCP schema must be attached');
    const item=calls===1?{type:'function_call',id:'fc_1',call_id:'call_1',name:found.name,...(found.namespace?{namespace:found.namespace}:{}),arguments:'{"command":"printf reference-ok"}',status:'completed'}:{type:'message',id:'msg_2',role:'assistant',status:'completed',content:[{type:'output_text',text:'done',annotations:[]}]};
    const response={id:'resp_'+calls,object:'response',created_at:1,model:body.model,status:'completed',output:[item],usage:{input_tokens:20,output_tokens:10,total_tokens:30}};
    events=[{type:'response.created',response:{...response,status:'in_progress',output:[]}},{type:'response.output_item.added',output_index:0,item},
     ...(calls===1?[{type:'response.function_call_arguments.done',item_id:item.id,output_index:0,arguments:item.arguments}]:[{type:'response.output_text.delta',item_id:item.id,output_index:0,content_index:0,delta:'done'}]),
     {type:'response.output_item.done',output_index:0,item},{type:'response.completed',response}];
   }
   if(calls>1)assert.match(JSON.stringify(body),/reference-ok/);
   yield{bytes:Buffer.from(events.map((e,i)=>'event: '+e.type+'\ndata: '+JSON.stringify({...e,sequence_number:i})+'\n\n').join('')).toString('base64')};
  }});
 const timer=setTimeout(()=>session.dispose(),75000);
 try{
  const exit=await session.exited;assert.equal(exit.code,0);assert.equal(tools,1);assert.equal(calls,2);
  const events=session.messages.filter(m=>m.method==='reference/event').map(m=>m.params);assert.ok(events.some(e=>e.type==='turn.completed'||e.type==='result'&&!e.is_error));
 }catch(error){throw evidence(root,error)}finally{clearTimeout(timer);await session.dispose();console.log('Reference '+harness+' evidence: '+root)}
});
