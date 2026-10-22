// Script-provider-only transport fixture. Exercises the real native SDK without
// Docker; it does NOT prove container isolation and must never run real models.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {randomUUID} from 'node:crypto';
import {DshSession} from '../../../src/execution/runner/dsh_session.mjs';

export async function localSessionFactory(){
 const channels=new Map();
 const server=http.createServer(async(req,res)=>{
  const [,id,operation]=req.url.split('/');const channel=channels.get(id);
  if(!channel){res.writeHead(404).end();return;}
  const abort=new AbortController();res.on('close',()=>abort.abort());
  try{
   let body='';for await(const chunk of req)body+=chunk;const payload=JSON.parse(body);
   res.writeHead(200,{'content-type':'application/x-ndjson'});
   const stream=operation==='model'?channel.gateway.stream(payload,abort.signal):channel.handler(operation,payload,abort.signal);
   for await(const result of stream)res.write(JSON.stringify({result})+'\n');res.end();
  }catch(error){res.end(JSON.stringify({error:error.message})+'\n');}
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 return {close:()=>new Promise(resolve=>server.close(resolve)),factory({executionRoot,logs,config,gateway,handler,mounts}){
  const id=randomUUID();channels.set(id,{gateway,handler});
  const locations=Object.fromEntries(mounts.map(m=>Object.fromEntries(m.split(',').map(pair=>pair.split('=')))).map(m=>[m.target,m.source]));
  const pluginRoot=locations['/opt/phyexp/meta-plugin'];
  const plugins=JSON.parse(JSON.stringify(config.plugins).replaceAll('/opt/phyexp/meta-plugin',pluginRoot));
  const patch=[{id:'llm-deepseek',disabled:true},
   {insert:[{id:'fixed-gateway',name:path.join(executionRoot,'runner/gateway_plugin.mjs')}]},
   {id:'tool-fs',config:{read:true,write:true,edit:true}},
   {id:'subprocess',disabled:true},
   {insert:[{id:'captured-subprocess',name:path.join(pluginRoot,'captured-subprocess.mjs')}]},
   {id:'sessions',config:{root:path.join(locations['/session'],'sessions'),compression:'none'}},
   {insert:plugins}];
  const file=path.join(logs,'fixture.patch.json');fs.writeFileSync(file,JSON.stringify(patch));
  const session=new DshSession({executable:process.execPath,args:[path.join(executionRoot,'runner/boot.mjs'),file],workspace:locations['/work'],home:locations['/session'],rpcLog:path.join(logs,'rpc.jsonl'),stderrLog:path.join(logs,'stderr.log'),
   environment:{PHYEXP_GATEWAY_URL:`http://127.0.0.1:${server.address().port}/${id}`,PHYEXP_MODEL_INFO:JSON.stringify(config.modelInfo),PHYEXP_FIXED_MODEL:JSON.stringify(config.fixedModel)}});
  const dispose=session.dispose.bind(session);
  session.dispose=async()=>{gateway.abort();await dispose();channels.delete(id);};return session;
 }};
}
