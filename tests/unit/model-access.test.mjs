import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {modelAccess,executionAccess} from '../../src/execution/host/model_access.mjs';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
const grant=()=>new Response(JSON.stringify({status:'granted'}));

test('a complete model response without usage permits subsequent calls without settlement',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-access-'));let calls=0;const urls=[];
 try{
  const access=modelAccess({deadline:Date.now()+10000,url:'http://controller/model-access/lease',token:'fixture',fetchImpl:async(url,options)=>{
   urls.push(url);assert.deepEqual(JSON.parse(options.body),{agentId:'main'});return grant();}});
  assert.equal(access.settle,undefined);assert.equal(access.snapshot,undefined);
  const gateway=new ModelGateway({model:{model:'fixed'},adapter:{async *stream(){calls++;yield {type:'finish',reason:{kind:'stop'}};}},
   deadline:Date.now()+10000,audit:path.join(dir,'audit.jsonl'),reserve:access.reserve});
  for(let i=0;i<3;i++)for await(const _ of gateway.stream({model:'fixed',sessionId:'main'})){}
  assert.equal(calls,3);assert.equal(urls.length,3);assert.ok(urls.every(u=>u.endsWith('/model-access/lease')));
  assert.equal(gateway.terminalFailure,null);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('storage and transient control waits retry only authorization and obey cancellation',async()=>{
 let tries=0;const states=[];
 const access=modelAccess({deadline:Date.now()+1000,url:'http://controller/access',retryMs:1,fetchImpl:async()=>{
  tries++;if(tries===1)return new Response('',{status:503});
  if(tries===2)return new Response(JSON.stringify({status:'waiting',code:'storage_capacity_wait'}),{status:429});
  return grant();}});
 await access.reserve('id',{}, {onState:s=>states.push(s.code)});
 assert.deepEqual(states,['control_unavailable','storage_capacity_wait']);assert.equal(tries,3);
 const cancel=new AbortController();cancel.abort();
 await assert.rejects(access.reserve('id',{}, {signal:cancel.signal}),{code:'request_cancelled'});
 assert.equal(tries,3);
 const expired=modelAccess({deadline:Date.now()-1});await assert.rejects(expired.reserve('id',{}),{code:'trial_deadline'});
});

test('auth denial and protocol errors cannot fall through to the provider',async()=>{
 for(const [code,status] of [['request_auth_failed',401],['request_lease_expired',401],['request_cancelled',403]]){
  let calls=0;const gate=modelAccess({deadline:Date.now()+1000,url:'http://controller/access',fetchImpl:async()=>{calls++;return new Response(JSON.stringify({code}),{status});}});
  await assert.rejects(gate.reserve('r',{}),{code});assert.equal(calls,1);
 }
 const gate=modelAccess({deadline:Date.now()+1000,url:'http://controller/access',fetchImpl:async()=>new Response('{}')});
 await assert.rejects(gate.reserve('r',{}),{code:'control_protocol_error'});
 assert.equal(executionAccess(Date.now()+1000,{}).snapshot,undefined);
});


test('reference wire gateway also accepts missing usage without a settlement callback',async()=>{
 const {WireGateway}=await import('../../src/execution/reference/wire.mjs');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-wire-access-'));let calls=0;
 try{
  const gate=modelAccess({deadline:Date.now()+1000});
  const gateway=new WireGateway({binding:{protocol:'responses',model:{model:'fixed'},baseURL:'http://fixture.invalid'},budget:gate,
   deadline:Date.now()+1000,audit:path.join(dir,'audit'),fetchImpl:async()=>{calls++;return new Response('{"output":[]}');}});
  for(let i=0;i<2;i++)for await(const _ of gateway.stream({method:'POST',path:'/responses',body:JSON.stringify({model:'fixed'})})){}
  assert.equal(calls,2);assert.equal(gateway.failure,undefined);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
