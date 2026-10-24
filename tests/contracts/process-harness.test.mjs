import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import zlib from 'node:zlib';
import {spawn} from 'node:child_process';
import {once} from 'node:events';

test('candidate DSH runs native tools and handles malformed output without platform mediation',async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-candidate-contract-'));
 const requests=[];
 const server=http.createServer(async(req,res)=>{
  let body='';for await(const bytes of req)body+=bytes;
  const call=JSON.parse(body);requests.push(call);
  const tools=call.messages.filter(m=>m.role==='tool');
  const step=requests.length;
  const toolName=call.tools?.find(t=>t.function.name==='bash')?.function.name;
  const name=tools.length?null:toolName;
  const arguments_=step===1?'x{':JSON.stringify({command:'printf candidate-native-tool'});
  res.writeHead(200,{'content-type':'text/event-stream'});
  const delta=name?{role:'assistant',tool_calls:[{index:0,id:'call-'+step,type:'function',function:{name,arguments:arguments_}}]}:{role:'assistant',content:'done'};
  for(const chunk of [{choices:[{index:0,delta,finish_reason:null}]},{choices:[{index:0,delta:{},finish_reason:name?'tool_calls':'stop'}]}])res.write('data: '+JSON.stringify({id:'fixture-'+step,object:'chat.completion.chunk',model:'fixture',...chunk})+'\n\n');
  res.end('data: [DONE]\n\n');
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const context={instruction:'Use bash to print candidate-native-tool.',workspace:root,outputDirectory:path.join(root,'output'),
   modelChannel:{protocol:'completions',url:'http://127.0.0.1:'+server.address().port,token:'fixture'},solver:{model:'fixture'},deadline:Date.now()/1000+60,mcpServers:[]};
 const file=path.join(root,'context.json');fs.writeFileSync(file,JSON.stringify(context));
 const child=spawn(process.execPath,['templates/harness/default/run.mjs'],{env:{...process.env,PHYEXP_CONTEXT:file},stdio:['ignore','pipe','pipe']});
 let stderr='';child.stderr.on('data',b=>stderr+=b);child.stdout.resume();
 const timer=setTimeout(()=>child.kill('SIGKILL'),55000);
 try{
  const [code]=await once(child,'exit');assert.equal(code,0,stderr);
  assert.ok(requests.length>=3,JSON.stringify({requests:requests.length,tools:requests[0]?.tools?.map(t=>t.function.name),events:JSON.parse(fs.readFileSync(path.join(root,'output/events.json'))).slice(-5),stderr}));
  assert.ok(requests.some(r=>r.messages.some(m=>m.role==='tool'&&JSON.stringify(m).includes('candidate-native-tool'))));
 }finally{clearTimeout(timer);server.closeAllConnections();server.close();fs.rmSync(root,{recursive:true,force:true});}
});

test('candidate uses catalog Codex protocol and accepts fractional external deadlines',async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-codex-contract-')),requests=[];
 const server=http.createServer(async(req,res)=>{
  const chunks=[];for await(const b of req)chunks.push(b);let bytes=Buffer.concat(chunks);if(req.headers['content-encoding']==='zstd')bytes=zlib.zstdDecompressSync(bytes);requests.push({path:req.url,body:JSON.parse(bytes)});
  const item={id:'msg1',type:'message',role:'assistant',status:'completed',content:[{type:'output_text',text:'completed',annotations:[]}]};
  const events=[{type:'response.created',response:{id:'r1',status:'in_progress',output:[]}},
   {type:'response.output_item.added',output_index:0,item:{...item,status:'in_progress',content:[]}},
   {type:'response.output_text.delta',output_index:0,content_index:0,delta:'completed'},
   {type:'response.output_item.done',output_index:0,item},
   {type:'response.completed',response:{id:'r1',status:'completed',output:[item],usage:{input_tokens:1,output_tokens:1,total_tokens:2}}}];
  res.writeHead(200,{'content-type':'text/event-stream'});for(const event of events)res.write('data: '+JSON.stringify(event)+'\n\n');res.end();
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const token='e30.'+Buffer.from(JSON.stringify({'https://api.openai.com/auth':{chatgpt_account_id:'trial'}})).toString('base64url')+'.fixture';
 const context={instruction:'Finish.',workspace:root,outputDirectory:path.join(root,'out'),modelChannel:{protocol:'responses',codexSubscription:true,url:'http://127.0.0.1:'+server.address().port,token},solver:{model:'gpt-6-sol',reasoningEffort:'high'},deadline:Date.now()/1000+60.1234567,mcpServers:[]};
 const file=path.join(root,'context.json');fs.writeFileSync(file,JSON.stringify(context));
 const child=spawn(process.execPath,['templates/harness/default/run.mjs'],{env:{...process.env,PHYEXP_CONTEXT:file},stdio:['ignore','pipe','pipe']});
 let stderr='';child.stderr.on('data',b=>stderr+=b);child.stdout.resume();const timer=setTimeout(()=>child.kill('SIGKILL'),55000);
 try{const [code]=await once(child,'exit');assert.equal(code,0,stderr);assert.equal(requests.length,1);assert.equal(requests[0].path,'/codex/responses');assert.equal(requests[0].body.model,'gpt-6-sol');assert.equal(requests[0].body.reasoning.effort,'high');assert.ok(!stderr.includes('did not activate'),stderr);}
 finally{clearTimeout(timer);server.closeAllConnections();server.close();fs.rmSync(root,{recursive:true,force:true});}
});
