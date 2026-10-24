import {test} from 'node:test';
import fs from 'node:fs';
import zlib from 'node:zlib';
import assert from 'node:assert/strict';
import {serve,fixedRequest} from '../../src/execution/process/broker.mjs';
const binding={model:{model:'fixed',reasoningEffort:'medium'},protocol:'responses',baseURL:'https://provider.invalid/v1',headers:{authorization:'Bearer secret'}};
test('fixed binding preserves native fields, dynamic tools and compact requests',()=>{
 for(const path of ['/responses','/responses/compact']){
  const request=fixedRequest(binding,path,{model:'fixed',input:[],tools:[],new_field:{x:1}});
  assert.deepEqual(request.body.new_field,{x:1});assert.deepEqual(request.body.tools,[]);
  assert.equal(request.body.reasoning.effort,'medium');assert.equal(request.url,'https://provider.invalid/v1'+path);
 }
 assert.throws(()=>fixedRequest(binding,'/responses',{model:'other'}),/mismatch/);
});
test('provider errors do not poison later requests or cause hidden retries',async()=>{
 let calls=0;
 const proxy=await serve({binding,token:'trial',deadline:Date.now()+10000,requestBytes:4096,
  fetchImpl:async(_url,request)=>{assert.equal(request.headers.authorization,'Bearer secret');calls++;
   return new Response(calls===1?'temporary':'data: {"malformed_arguments":"{xx"}\n\n',{status:calls===1?503:200,headers:{'content-type':'text/event-stream'}});}});
 try{
  const call=()=>fetch(proxy.url+'/responses',{method:'POST',headers:{authorization:'Bearer trial'},body:JSON.stringify({model:'fixed',tools:[]})});
  const first=await call();assert.equal(first.status,503);await first.text();
  const second=await call();assert.equal(second.status,200);assert.match(await second.text(),/malformed_arguments/);assert.equal(calls,2);
 }finally{await proxy.close();}
});
test('short credential, model and declared request capacity enforced locally',async()=>{
 let calls=0;
 const proxy=await serve({binding,token:'trial',deadline:Date.now()+10000,requestBytes:80,fetchImpl:async()=>{calls++;return new Response('ok');}});
 try{
  for(const [token,body,status] of [['bad',{model:'fixed'},401],['trial',{model:'other'},403],['trial',{model:'fixed',input:'x'.repeat(100)},413]]){
   const r=await fetch(proxy.url+'/responses',{method:'POST',headers:{authorization:'Bearer '+token},body:JSON.stringify(body)});
   assert.equal(r.status,status);await r.text();
  }
  assert.equal(calls,0);
 }finally{await proxy.close();}
});
test('revocation cancels an in-flight request without contacting the controller',async()=>{
 let started;const ready=new Promise(resolve=>started=resolve);
 let aborted=false;
 const proxy=await serve({binding,token:'trial',deadline:Date.now()+10000,requestBytes:4096,
  fetchImpl:async(_url,{signal})=>{started();return new Promise((_,reject)=>signal.addEventListener('abort',()=>{aborted=true;reject(new Error('cancelled'));},{once:true}));}});
 const request=fetch(proxy.url+'/responses',{method:'POST',headers:{authorization:'Bearer trial'},body:'{"model":"fixed"}'}).catch(()=>null);
 await ready;proxy.revoke();await request;assert.equal(aborted,true);await proxy.close();
});

test('native compressed requests are decoded within declared capacity, with no stale encoding',async()=>{
 let calls=0;const proxy=await serve({binding,token:'trial',deadline:Date.now()+10000,requestBytes:4096,
  fetchImpl:async(_url,request)=>{calls++;assert.equal(request.headers['content-encoding'],undefined);assert.equal(JSON.parse(request.body).model,'fixed');return new Response('ok');}});
 try{for(const [input,status] of [[{model:'fixed'},200],[{model:'fixed',input:'a'.repeat(10000)},413]]){
  const response=await fetch(proxy.url+'/codex/responses',{method:'POST',headers:{authorization:'Bearer trial','content-encoding':'zstd'},body:zlib.zstdCompressSync(JSON.stringify(input))});assert.equal(response.status,status);await response.text();
 }assert.equal(calls,1);}finally{await proxy.close();}
});

test('concurrent auxiliary sessions and responses larger than 32 MiB remain transparent',async()=>{
 let calls=0;const size=34*1024*1024,chunk=new Uint8Array(65536).fill(97);
 const proxy=await serve({binding,token:'trial',deadline:Date.now()+30000,requestBytes:40*1024*1024,
  fetchImpl:async(_url,request)=>{calls++;const body=JSON.parse(request.body);if(!body.large)return new Response('ok');let sent=0;
   return new Response(new ReadableStream({pull(controller){if(sent===size)controller.close();else{controller.enqueue(chunk);sent+=chunk.length;}}}));}});
 try{
  const request=body=>fetch(proxy.url+'/responses',{method:'POST',headers:{authorization:'Bearer trial'},body:JSON.stringify({model:'fixed',...body})});
  const replies=await Promise.all(Array.from({length:20},(_,i)=>request({input:[],tools:i%2?[]:[{type:'function',name:'new_tool_'+i,parameters:{type:'object'}}]})));
  for(const reply of replies){assert.equal(reply.status,200);await reply.text();}
  const large=await request({large:true,input:'x'.repeat(33*1024*1024)});assert.equal(large.status,200);
  let received=0;for await(const bytes of large.body){received+=bytes.length;if(received%(1024*1024)===0)await new Promise(r=>setTimeout(r,2));}
  assert.equal(received,size);assert.equal(calls,21);
 }finally{await proxy.close();}
});

test('audit storage failure is a bounded channel failure and never becomes an unhandled rejection',async()=>{
 let calls=0;const proxy=await serve({binding,token:'trial',deadline:Date.now()+10000,requestBytes:4096,audit:'/dev/full',
  fetchImpl:async()=>{calls++;return new Response('ok');}});
 try{const original=fs.appendFileSync;fs.appendFileSync=()=>{throw Object.assign(new Error('disk full'),{code:'ENOSPC'});};
  try{const response=await fetch(proxy.url+'/responses',{method:'POST',headers:{authorization:'Bearer trial'},body:'{"model":"fixed"}'});
   assert.equal(response.status,507);assert.match(await response.text(),/ENOSPC/);assert.equal(calls,0);
  }finally{fs.appendFileSync=original;}
 }finally{await proxy.close();}
});
