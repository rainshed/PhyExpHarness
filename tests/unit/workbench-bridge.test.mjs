import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {Readable} from 'node:stream';
import {apply} from '../../packages/meta-workbench-bridge/index.mjs';

function bridge(base='http://127.0.0.1:1'){
 const previous={PHYEXP_CONTROL_URL:process.env.PHYEXP_CONTROL_URL,PHYEXP_USER_TOKEN:process.env.PHYEXP_USER_TOKEN};
 let route;
 try{
  process.env.PHYEXP_CONTROL_URL=base;process.env.PHYEXP_USER_TOKEN='fixture-only';
  apply({connection:{requestRejection:()=>undefined},effect:fn=>fn(),webServer:{register:value=>{route=value;return()=>{}}}});
 }finally{
  for(const [key,value] of Object.entries(previous))if(value===undefined)delete process.env[key];else process.env[key]=value;
 }
 return async(path,body)=>{
  const req=Object.assign(Readable.from(body===undefined?[]:[JSON.stringify(body)]),{
   method:body===undefined?'GET':'POST',url:'/phyexp/api'+path,headers:{host:'workbench.example',origin:'http://workbench.example'}});
  const res={heads:[],writeHead(status,headers){this.status=status;this.headers=headers;this.heads.push(status);return this},end(body){this.body=JSON.parse(String(body));return this}};
  await route.handler(req,res);return res;
 };
}

test('start response after the old 20-second deadline reaches the UI exactly once',{timeout:30000},async t=>{
 let calls=0,timer;
 const server=http.createServer(async(req,res)=>{
  calls++;assert.equal(req.headers.authorization,'Bearer fixture-only');
  let body='';for await(const chunk of req)body+=chunk;
  assert.deepEqual(JSON.parse(body),{action:'start',expectedRevision:3,idempotencyKey:'same-attempt'});
  timer=setTimeout(()=>res.writeHead(200,{'content-type':'application/json'}).end(JSON.stringify({state:'running'})),21000);
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(async()=>{clearTimeout(timer);server.closeAllConnections();await new Promise(resolve=>server.close(resolve))});
 const invoke=bridge('http://127.0.0.1:'+server.address().port);
 const response=await invoke('/campaigns/campaign-fixture/control',{action:'start',expectedRevision:3,idempotencyKey:'same-attempt'});
 assert.equal(response.status,200);assert.equal(response.body.state,'running');assert.equal(calls,1);
});

test('control waits longer while reads retain their deadline and backend refusals stay intact',async t=>{
 const deadlines=[];
 t.mock.method(AbortSignal,'timeout',ms=>{deadlines.push(ms);return new AbortController().signal});
 t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({error:'Campaign revision changed'}),{status:409}));
 const invoke=bridge();
 for(const action of ['start','resume','stop']){
  const response=await invoke('/campaigns/campaign-fixture/control',{action});
  assert.equal(response.status,409);assert.equal(response.body.error,'Campaign revision changed');
 }
 await invoke('/campaigns/campaign-fixture');
 await invoke('/campaigns/campaign-fixture/plan',{changes:{}});
 assert.deepEqual(deadlines,[120000,120000,120000,20000,20000]);
});

test('a timed-out command reports an unknown outcome without retrying',async t=>{
 let calls=0;
 t.mock.method(globalThis,'fetch',async()=>{calls++;throw new DOMException('The operation was aborted due to timeout','TimeoutError')});
 const response=await bridge()('/campaigns/campaign-fixture/control',{action:'start',idempotencyKey:'same-attempt'});
 assert.equal(response.status,504);assert.equal(response.headers['cache-control'],'no-store');
 assert.match(response.body.error,/结果尚未确认.*后台可能仍在处理.*不要重复提交/);
 assert.equal(response.body.code,'control_response_timeout');assert.equal(calls,1);
});

test('timeout while reading a response body sends one complete error response',async t=>{
 t.mock.method(globalThis,'fetch',async()=>({status:200,headers:new Headers(),arrayBuffer:async()=>{throw new DOMException('timeout','TimeoutError')}}));
 const response=await bridge()('/campaigns/campaign-fixture');
 assert.deepEqual(response.heads,[504]);assert.match(response.body.error,/读取后台状态超时/);
 assert.doesNotMatch(response.body.error,/操作结果/);
});

test('an unavailable backend remains a service error',async t=>{
 t.mock.method(globalThis,'fetch',async()=>{throw new TypeError('fetch failed')});
 const response=await bridge()('/health');
 assert.equal(response.status,503);assert.equal(response.body.error,'fetch failed');
});
