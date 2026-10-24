import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
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
