import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {JsonPrefix,StreamGuard} from '../../src/execution/host/stream_guard.mjs';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
const delta=s=>({type:'tool-call-delta',index:0,argumentsDelta:s});
const model={provider:'fixture',model:'fixture'};
function gateway(adapter,policy={}){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'stream-test-'));const settled=[];
 return {dir,settled,g:new ModelGateway({model,adapter,policy:{...policy,cleanupGraceMs:20},deadline:Date.now()+10000,audit:path.join(dir,'audit.jsonl'),settle:async(id,x)=>settled.push(x)})};}
async function run(g){for await(const _ of g.stream(model)){} }
test('valid JSON prefixes, escaped strings, nesting, literals and split unicode are accepted',()=>{
 const values=[{}, {command:'a\n"\\\u0001'}, {a:[1,-1.2e3,true,false,null,{},[]]}, {long:'x'.repeat(80000)}];
 for(const value of values){const text=JSON.stringify(value),p=new JsonPrefix();for(const c of text)p.push(c);assert.ok(p.complete());}
 for(const text of ['{"a":','{"a":"unfinished','{"a":[1,','{"a":"\\u00']){const p=new JsonPrefix();p.push(text);assert.equal(p.complete(),false);}
 for(const text of ['{"a":1,}', '{"a":1}garbage','{"a":NaN}','{"a":"\n"}','{"a":[1,]}'])assert.throws(()=>new JsonPrefix().push(text));
});
test('large ordinary code and partial JSON are not mistaken for anomalies',()=>{
 const g=new StreamGuard({},0),s=JSON.stringify({command:'print("hello")\n'.repeat(5000)});
 for(let i=0;i<s.length;i+=211)assert.equal(g.accept(delta(s.slice(i,i+211)),i),null);
 assert.equal(g.accept({type:'block-end',index:0,block:{type:'tool-call',arguments:s}},100000),null);
});
test('whitespace protection requires both duration and length; counters survive chunk splits',()=>{
 const g=new StreamGuard({},0);assert.equal(g.accept(delta('{"command":"'+ ' '.repeat(5000)),1000),null);
 assert.equal(g.accept(delta(' '),30999),null);assert.equal(g.accept(delta(' '),31000).code,'stream_whitespace');
 const reset=new StreamGuard({},0);reset.accept(delta('{"x":"'+ ' '.repeat(5000)),0);reset.accept(delta('x'),40000);assert.equal(reset.accept(delta(' '),41000),null);
});
test('invalid syntax and byte limits terminate with distinct causes; unicode is counted as UTF-8',()=>{
 assert.equal(new StreamGuard({},0).accept(delta('{"x":1,}'),1).code,'invalid_tool_arguments');
 assert.equal(new StreamGuard({maxToolArgumentBytes:10},0).accept(delta('{"x":"中文"}'),1).code,'tool_argument_size_limit');
 assert.equal(new StreamGuard({maxResponseBytes:5},0).accept({type:'text-delta',text:'中文'},1).code,'response_size_limit');
});
test('repetitive valid data only warns, and incomplete final arguments cannot execute',()=>{
 const g=new StreamGuard({},0);assert.equal(g.accept(delta('{"x":"'),0),null);assert.equal(g.accept(delta('a'.repeat(5000)),100),null);assert.equal(g.warnings.length,1);
 assert.equal(g.accept({type:'block-end',index:0,block:{type:'tool-call',arguments:'{}'}},101).code,'invalid_tool_arguments');
});
test('guard cause is durable before cancellation; late real receipt is settled exactly once',async()=>{
 let cancelled=false;const x=gateway({async *stream({signal}){yield delta('{"x":}');cancelled=signal.aborted;yield {type:'usage',usage:{totalTokens:17}};yield {type:'finish',reason:{kind:'stop'}};}});
 try{await assert.rejects(run(x.g),/invalid_tool_arguments/);assert.ok(cancelled);assert.equal(x.settled.length,1);assert.equal(x.settled[0].usage.totalTokens,17);
  assert.equal(JSON.parse(fs.readFileSync(path.join(x.dir,'failure.json'))).code,'invalid_tool_arguments');await assert.rejects(run(x.g),/invalid_tool_arguments/);assert.equal(x.settled.length,1);
 }finally{fs.rmSync(x.dir,{recursive:true,force:true});}
});
test('no data and uncooperative adapter are bounded by request timeout with unknown usage',async()=>{
 const x=gateway({async *stream(){await new Promise(()=>{});}},{requestTimeoutMs:20});
 try{await assert.rejects(run(x.g),/cancel/);assert.equal(x.g.firstFailure.code,'request_timeout');assert.equal(x.settled[0].usage,null);}finally{fs.rmSync(x.dir,{recursive:true,force:true});}
});
test('idle timeout after progress differs from total request timeout',async()=>{
 const x=gateway({async *stream(){yield {type:'text-delta',text:'hello'};await new Promise(()=>{});}},{streamIdleTimeoutMs:20});
 try{await assert.rejects(run(x.g),/cancel/);assert.equal(x.g.firstFailure.code,'stream_idle_timeout');}finally{fs.rmSync(x.dir,{recursive:true,force:true});}
});
test('idle timeout also bounds the wait for the first response',async()=>{
 const x=gateway({async *stream(){await new Promise(()=>{});}},{streamIdleTimeoutMs:20});
 try{await assert.rejects(run(x.g),/cancel/);assert.equal(x.g.firstFailure.code,'stream_idle_timeout');}finally{fs.rmSync(x.dir,{recursive:true,force:true});}
});
test('completed provider max-tokens retains actual usage and explicit failure',async()=>{
 const x=gateway({async *stream(){yield {type:'usage',usage:{totalTokens:128100}};yield {type:'finish',reason:{kind:'max-tokens'}};}});
 try{await run(x.g);assert.equal(x.g.firstFailure.code,'model_output_limit');assert.equal(x.settled[0].usage.totalTokens,128100);}finally{fs.rmSync(x.dir,{recursive:true,force:true});}
});
test('non-delta text blocks are bounded and normal end blocks do not count twice',()=>{
 const a=new StreamGuard({maxResponseBytes:4});assert.equal(a.accept({type:'block-end',index:0,block:{type:'text',text:'12345'}}).code,'response_size_limit');
 const b=new StreamGuard({maxResponseBytes:4});b.accept({type:'text-delta',index:0,text:'1234'});assert.equal(b.accept({type:'block-end',index:0,block:{type:'text',text:'1234'}}),null);
});
