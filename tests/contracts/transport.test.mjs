import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {isolatedSession} from '../../src/execution/host/isolation.mjs';
import {forwardMcp} from '../../src/execution/host/capabilities.mjs';
const model={provider:'openai-codex',model:'gpt-6-sol',reasoningEffort:'medium',maxTokens:8192};
test('native MCP schemas, Unicode and large output survive network-none stdio transport', {timeout:45000}, async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-transport-'));const calls=[];let receipt,requests=0;
 const nativeTool={name:'echo',description:'Original public tool description.',inputSchema:{type:'object',properties:{value:{type:'string'}},required:['value']}};
 const server=http.createServer(async(req,res)=>{
  if(req.method!=='POST'){res.writeHead(405).end();return;}
  let text='';for await(const c of req)text+=c;const msg=JSON.parse(text);calls.push(msg);
  if(msg.id===undefined){res.writeHead(202).end();return;}
  const result=msg.method==='initialize'?{protocolVersion:'2025-03-26',capabilities:{tools:{}},serverInfo:{name:'fixture',version:'1'},instructions:'Public fixture source.'}:
    msg.method==='tools/list'?{tools:[nativeTool]}:msg.method==='tools/call'?{content:[{type:'text',text:msg.params.arguments.value}]}:{};
  res.writeHead(200,{'content-type':'application/json'}).end(JSON.stringify({jsonrpc:'2.0',id:msg.id,result}));
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const connections=[{name:'qsim',transport:'streamable-http',url:`http://127.0.0.1:${server.address().port}`,toolNames:['echo'],toolCallTimeoutMs:5000}];
 const adapter={async *stream(request){requests++;
  if(requests<=2){const name=requests===1?'mcp__qsim__echo':'bash';const args=requests===1?{value:'中文字符✓'}:{command:'literal $(not-on-host)'};
   assert.ok(request.tools.some(t=>t.name==='mcp__qsim__echo'&&t.description.includes(nativeTool.description)));
   yield {type:'block-start',index:0,blockType:'tool-call'};yield {type:'block-end',index:0,block:{type:'tool-call',id:'call'+requests,name,arguments:JSON.stringify(args)}};
   yield {type:'finish',reason:{kind:'tool-calls'}};
  }else{assert.match(JSON.stringify(request.messages),/中文字符✓/);assert.match(JSON.stringify(request.messages),/Output clipped/);
   yield {type:'block-start',index:0,blockType:'text'};yield {type:'block-end',index:0,block:{type:'text',text:'done'}};yield {type:'finish',reason:{kind:'stop'}};}
 }};
 const gateway=new ModelGateway({model,adapter,deadline:Date.now()+40000,audit:path.join(dir,'gateway.jsonl')});
 const session=isolatedSession({executionRoot:'src/execution',logs:dir,gateway,config:{disableLocalTools:true,mcpConnections:connections,
  modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},
  plugins:[{id:'container-tools',name:'/opt/phyexp/src/execution/adapters/quantum_harbor/container_tool.mjs'}]},
  async *handler(op,payload,signal){if(op==='mcp')yield*forwardMcp(connections,payload,signal);
   else if(op==='receipt'){receipt=payload;yield {ok:true};}
   else if(op==='tool'){assert.equal(payload.command,'literal $(not-on-host)');yield {stdout:'x'.repeat(100000),stderr:'',returnCode:0};}
   else throw new Error('denied');}
 });
 try{await session.request('initialize',{...model,cwd:'/tmp/work'});assert.ok(receipt.tools.includes('mcp__qsim__echo'));
  const events=await session.prompt('transport','Exercise available tools.',30000);assert.equal(requests,3);assert.equal(events.filter(e=>e.type==='tool/result').length,2);
  assert.ok(calls.some(m=>m.method==='tools/call'));assert.deepEqual(await session.shutdown(),{code:0,signal:null});
 }catch(e){throw new Error(e.stack+'\n'+fs.readFileSync(path.join(dir,'stderr.log'),'utf8'));}
 finally{await session.dispose();server.closeAllConnections();await new Promise(r=>server.close(r));console.log('MCP evidence: '+dir);}
});
