// Credential and fixed-model boundary. No agent loop, output guard or retry policy.
import http from 'node:http';
import fs from 'node:fs';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
import {once} from 'node:events';
import {pathToFileURL} from 'node:url';

const forbidden = new Set(['authorization','proxy-authorization','cookie','host','connection','content-length','content-encoding','transfer-encoding','chatgpt-account-id','originator','x-api-key']);
export function fixedRequest(binding, url, body) {
 const path = new URL(url,'http://local').pathname.replace(/^\/codex\//,'/');
 const paths = binding.protocol === 'responses' ? ['/responses','/responses/compact','/v1/responses','/v1/responses/compact'] :
   binding.protocol === 'anthropic' ? ['/v1/messages','/v1/messages/count_tokens','/messages','/messages/count_tokens'] : ['/chat/completions','/v1/chat/completions'];
 if(!paths.includes(path)) throw Object.assign(new Error('Unsupported provider endpoint'),{status:404});
 if(body.model !== binding.model.model) throw Object.assign(new Error('Fixed model mismatch'),{status:403});
 const effort=binding.model.reasoningEffort, cap=binding.model.maxTokens;
 if(binding.protocol==='responses'){
  if(effort!==undefined)body.reasoning={...body.reasoning,effort};
  if(cap!==undefined)body.max_output_tokens=cap;
 } else if(binding.protocol==='anthropic') {
  if(cap!==undefined)body.max_tokens=cap;
  if(effort!==undefined){
   body.thinking={type:effort==='off'?'disabled':binding.deepseek?'enabled':'adaptive'};
   if(effort!=='off')body.output_config={...body.output_config,effort};
  }
 } else {
  if(cap!==undefined)body.max_tokens=cap;
  if(effort!==undefined)body.reasoning_effort=effort;
 }
 // These are subscription protocol requirements, not Harness strategies.
 if(binding.codexSubscription){body.store=false;delete body.max_output_tokens;}
 const root=binding.baseURL.replace(/\/+$/,'');
 const route=path.startsWith('/v1/') ? path.slice(3) : path;
 return {url:root+(root.endsWith('/v1')||binding.protocol!=='anthropic'?route:'/v1'+route),body};
}

export async function serve({binding,token,deadline,requestBytes,port=0,host='127.0.0.1',audit,fetchImpl=fetch}) {
 if(!Number.isFinite(deadline)||!Number.isSafeInteger(requestBytes)||requestBytes<1)throw new Error('Explicit deadline and request capacity required');
 const active=new Set();let revoked=false;
 const record=row=>{if(audit){try{fs.appendFileSync(audit,JSON.stringify({time:new Date().toISOString(),...row})+'\n');}
  catch(error){throw Object.assign(new Error('Model channel audit failed: '+(error.code||error.name)),{status:507,code:error.code});}}};
 const server=http.createServer(async(req,res)=>{
  const id=crypto.randomUUID(),ctl=new AbortController();active.add(ctl);
  res.on('close',()=>{if(!res.writableEnded)ctl.abort();});
  try{
   if(revoked||Date.now()>=deadline)throw Object.assign(new Error('Trial lease expired or revoked'),{status:410});
   if(req.headers.authorization!=='Bearer '+token && req.headers['x-api-key']!==token)throw Object.assign(new Error('Trial credential required'),{status:401});
   if(req.method==='GET'&&['/models','/v1/models'].includes(req.url)){
    res.setHeader('content-type','application/json');res.end(JSON.stringify({data:[{id:binding.model.model,object:'model'}]}));return;
   }
   if(req.method!=='POST')throw Object.assign(new Error('Model POST required'),{status:405});
   const chunks=[];let size=0;
   for await(const chunk of req){size+=chunk.length;if(size>requestBytes)throw Object.assign(new Error('Declared request capacity exceeded'),{status:413});chunks.push(chunk);}
   let bytes=Buffer.concat(chunks);
   const encoding=req.headers['content-encoding'];
   if(encoding&&encoding!=='identity'){
    const decode={zstd:zlib.zstdDecompressSync,gzip:zlib.gunzipSync,deflate:zlib.inflateSync,br:zlib.brotliDecompressSync}[encoding];
    if(!decode)throw Object.assign(new Error('Unsupported request content encoding'),{status:415});
    try{bytes=decode(bytes,{maxOutputLength:requestBytes});}
    catch(error){throw Object.assign(error,{status:error.code==='ERR_BUFFER_TOO_LARGE'?413:400});}
   }
   let body;try{body=JSON.parse(bytes.toString());}catch{throw Object.assign(new Error('Invalid request JSON'),{status:400});}
   const request=fixedRequest(binding,req.url,body);
   record({type:'request',id,endpoint:req.url,body:request.body});
   const headers=Object.fromEntries(Object.entries(req.headers).filter(([k])=>!forbidden.has(k)));
   Object.assign(headers,binding.headers,{'content-type':'application/json'});
   const upstream=await fetchImpl(request.url,{method:'POST',headers,body:JSON.stringify(request.body),signal:ctl.signal,redirect:'error'});
   const output=Object.fromEntries([...upstream.headers].filter(([k])=>!['content-length','transfer-encoding','connection','content-encoding','set-cookie'].includes(k)));
   res.writeHead(upstream.status,output);record({type:'response',id,status:upstream.status});
   for await(const bytes of upstream.body){
    record({type:'chunk',id,bytes:Buffer.from(bytes).toString('base64')});
    if(!res.write(bytes))await once(res,'drain',{signal:ctl.signal});
   }
   res.end();record({type:'end',id});
  }catch(error){
   ctl.abort();
   try{record({type:'error',id,code:error.code||error.name,message:error.message});}
   catch{process.stderr.write(JSON.stringify({stage:'model-channel-audit',code:error.code,message:error.message})+'\n');}
   if(!res.headersSent){res.writeHead(error.status||502,{'content-type':'application/json'});res.end(JSON.stringify({error:{message:error.message}}));}
   else res.destroy(error);
  }finally{active.delete(ctl);}
 });
 // The original Trial deadline is enforced here without control-service heartbeats.
 const revoke=()=>{revoked=true;for(const ctl of active)ctl.abort();server.closeAllConnections();server.close();};
 server.on('upgrade',(_request,socket)=>{socket.end('HTTP/1.1 426 Upgrade Required\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nThis model channel supports HTTP/SSE; WebSocket is unavailable.');});
 const timer=setTimeout(revoke,Math.max(1,deadline-Date.now()));timer.unref();
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,host,resolve);});
 return {server,url:`http://${host}:${server.address().port}`,revoke,close:async()=>{clearTimeout(timer);revoke();}};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 const config=JSON.parse(fs.readFileSync(process.argv[2]));
 const broker=await serve({...config,host:'0.0.0.0',port:8080});
 console.log(JSON.stringify({ready:true,port:8080}));
 for(const signal of ['SIGTERM','SIGINT'])process.once(signal,async()=>{await broker.close();process.exit(0);});
}
