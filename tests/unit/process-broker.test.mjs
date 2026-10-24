import {test} from 'node:test';
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
