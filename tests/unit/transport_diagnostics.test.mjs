import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {gzipSync} from 'node:zlib';
import {WebSocketServer} from 'ws';
import {Context} from '@deepseek-ai/cordis';
import {LlmRuntime} from '@deepseek-ai/dsh-llm';
import LocalCredentials from '@deepseek-ai/dsh-credentials-local';
import * as PiAi from '@deepseek-ai/dsh-llm-pi-ai';
import {closeOpenAICodexWebSocketSessions} from '@earendil-works/pi-ai/api/openai-codex-responses';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {TransportDiagnostics} from '../../src/execution/host/transport_diagnostics.mjs';

const model={provider:'openai-codex',model:'gpt-6-luna',reasoningEffort:'xhigh',maxTokens:8192};
function responseEvents(){
 const item={type:'message',id:'msg_fixture',role:'assistant',status:'completed',
  content:[{type:'output_text',text:'PRIVATE_RESPONSE_TEXT',annotations:[]}]};
 return [
  {type:'response.created',response:{id:'resp_fixture',status:'in_progress'}},
  {type:'response.output_item.added',output_index:0,item:{...item,status:'in_progress',content:[]}},
  {type:'response.output_text.delta',output_index:0,content_index:0,delta:'PRIVATE_RESPONSE_TEXT'},
  {type:'response.output_item.done',output_index:0,item},
  {type:'response.completed',response:{id:'resp_fixture',status:'completed',output:[item],
   usage:{input_tokens:10,output_tokens:2,total_tokens:12}}}
 ];
}
async function fixture(t,behavior){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-transport-'));
 const counts={websocket:0,sse:0},settlements=[],wireMessages=[];
 const server=http.createServer((req,res)=>{
  counts.sse++;req.resume();
  if(behavior==='exhausted'){res.writeHead(503);res.end('{"error":{"message":"server overloaded"}}');return;}
  res.writeHead(200,behavior==='sse-no-content-type'?{}:{'content-type':'text/event-stream',
   ...(behavior==='sse-gzip'?{'content-encoding':'gzip'}:{})});
  const events=responseEvents().map(e=>'data: '+JSON.stringify(e)+'\n\n').join('');
  if(behavior==='sse-gzip'){res.end(gzipSync(events));return;}
  // Protocol metadata must survive fragmented UTF-8/SSE lines.
  res.write(events.slice(0,12));setTimeout(()=>res.end(events.slice(12)),5);
 });
 const wss=new WebSocketServer({server});
 wss.on('connection',ws=>ws.on('message',data=>{
  counts.websocket++;wireMessages.push(JSON.parse(String(data)));
  if(behavior==='success'){
   for(const event of responseEvents())ws.send(JSON.stringify(event));
   return;
  }
  if(behavior!=='before-start')ws.send(JSON.stringify(responseEvents()[0]));
  setTimeout(()=>{
   if(behavior==='clean-close')ws.close(1012,'service restart Bearer DO_NOT_LOG');
   else ws.terminate();
  },10);
 }));
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const originalFetch=globalThis.fetch;
 globalThis.fetch=(input,init)=>{
  const url=new URL(typeof input==='string'||input instanceof URL?input:input.url);
  assert.equal(url.hostname,'127.0.0.1','Offline test must never contact a real provider or refresh service');
  return originalFetch(input,init);
 };
 const token='fixture.'+Buffer.from(JSON.stringify({'https://api.openai.com/auth':{chatgpt_account_id:'fixture'}})).toString('base64url')+'.signature';
 const credentials=path.join(dir,'credentials.json');
 fs.writeFileSync(credentials,JSON.stringify({version:1,refs:{},records:{
  'llm-pi-ai/openai-codex':{kind:'grant',payload:{type:'oauth',access:token,refresh:'',expires:Date.now()+3600000}}
 }}),{mode:0o600});
 const ctx=new Context();
 t.after(async()=>{
  closeOpenAICodexWebSocketSessions();
  await ctx.fiber.dispose();
  for(const ws of wss.clients)ws.terminate();
  await new Promise(resolve=>wss.close(resolve));
  await new Promise(resolve=>server.close(resolve));
  globalThis.fetch=originalFetch;fs.rmSync(dir,{recursive:true,force:true});
 });
 await ctx.plugin(LlmRuntime).await();
 await ctx.plugin(LocalCredentials,{path:credentials,watch:false}).await();
 await ctx.plugin(PiAi,{providers:{'openai-codex':{
  baseURL:`http://127.0.0.1:${server.address().port}`,
  ...(behavior.startsWith('sse-')?{transport:'sse'}:{}),
  models:[{id:model.model,reasoningEfforts:{xhigh:'xhigh'}}],retryPolicy:{mode:'normal',maxRetries:0}
 }}}).await();
 const audit=path.join(dir,'audit.jsonl');
 const gateway=new ModelGateway({model,deadline:Date.now()+10000,audit,
  redact:value=>String(value).split(token).join('[REDACTED]'),
  adapter:{transport:'auto',stream:request=>ctx.llm.stream(request)},settle:async(id,result)=>settlements.push({id,...result})});
 const request=sessionId=>({...model,sessionId:path.basename(dir)+'-'+sessionId,messages:[{role:'user',content:[{type:'text',text:'PRIVATE_PROMPT'}]}],tools:[]});
 const call=async(sessionId='fixture-session')=>{const chunks=[];for await(const c of gateway.stream(request(sessionId)))chunks.push(c);return chunks;};
 const records=()=>fs.readFileSync(audit,'utf8').trim().split('\n').map(JSON.parse);
 return {gateway,call,counts,settlements,records,wireMessages};
}

test('after-start disconnect preserves zero content, protocol start, close code and explicit recovery',async t=>{
 const f=await fixture(t,'after-start');const first=await f.call();
 assert.equal(first.at(-1).reason.failure.code,'TRANSPORT');
 const failed=f.gateway.diagnostics({status:'error',turnEnd:{kind:'error',error:first.at(-1).reason.failure}});
 const observed=failed.failure.observed;
 assert.equal(observed.responseContentBytes,0);
 assert.equal(observed.responseBytesMeaning,'model-content-not-wire');
 assert.equal(observed.transport.protocolStarted,true);
 assert.equal(observed.transport.closeCode,1006);
 assert.equal(observed.transport.wasClean,false);
 assert.equal(observed.transport.actualTransport,'websocket');
 assert.ok(observed.transport.receivedBodyBytes>0);
 assert.equal(f.counts.sse,0,'Do not add automatic same-request retry after start');
 assert.equal(f.gateway.terminalFailure,null);
 const second=await f.call();assert.equal(second.at(-1).reason.kind,'stop');
 const final=f.gateway.persistFinal({status:'completed',turnEnd:{kind:'completed'}});
 assert.equal(final.failure,null);assert.equal(final.requestRecovery.recoveredRequests,1);
 assert.equal(f.counts.sse,1);assert.equal(f.settlements.length,2);
 assert.equal(f.settlements[0].finish.kind,'error');assert.equal(f.settlements[1].usage.totalTokens,12);
 const transport=f.records().filter(r=>r.type==='transport');
 assert.ok(transport.some(r=>r.event==='protocol_started'));
 assert.ok(transport.some(r=>r.event==='websocket_close'&&r.closeCode===1006));
 assert.ok(transport.some(r=>r.event==='request_transport_end'&&r.actualTransport==='sse'&&r.protocolStarted));
 assert.ok(!JSON.stringify(transport).includes('PRIVATE_PROMPT'));
 assert.ok(!JSON.stringify(transport).includes('PRIVATE_RESPONSE_TEXT'));
});
test('before-start disconnect records WebSocket-to-SSE fallback without a failed logical request',async t=>{
 const f=await fixture(t,'before-start');const chunks=await f.call();
 assert.equal(chunks.at(-1).reason.kind,'stop');
 assert.deepEqual(f.counts,{websocket:1,sse:1});
 assert.equal(f.gateway.firstFailure,null);
 const end=f.records().find(r=>r.type==='transport'&&r.event==='request_transport_end');
 assert.equal(end.actualTransport,'sse');assert.equal(end.fallbackToSse,true);
 assert.equal(end.protocolStarted,true);assert.equal(end.closeCode,1006);
});
test('explicit recovery exhaustion keeps final overload failure and both request records',async t=>{
 const f=await fixture(t,'exhausted');await f.call();const last=await f.call();
 const final=f.gateway.persistFinal({status:'error',turnEnd:{kind:'error',error:last.at(-1).reason.failure}});
 assert.equal(final.failure.code,'model_service_overloaded');
 assert.equal(final.requestRecovery.failedRequests,2);assert.equal(final.requestRecovery.recoveredRequests,0);
 assert.equal(final.failure.observed.transport.httpStatus,503);
 assert.equal(f.settlements.length,2);
});
test('clean service-restart close is recoverable transport failure and audit reason is redacted',async t=>{
 const f=await fixture(t,'clean-close');const chunks=await f.call();
 assert.equal(chunks.at(-1).reason.failure.code,'TRANSPORT');
 const final=f.gateway.persistFinal({status:'error',turnEnd:{kind:'error',error:chunks.at(-1).reason.failure}});
 assert.equal(final.failure.code,'model_transport_error');
 assert.equal(final.failure.observed.transport.closeCode,1012);
 assert.equal(final.failure.observed.transport.wasClean,true);
 const transport=f.records().filter(r=>r.type==='transport');
 assert.ok(!JSON.stringify(transport).includes('DO_NOT_LOG'));
 assert.match(transport.find(r=>r.event==='websocket_close').closeReason,/REDACTED/);
});
test('concurrent connections and reuse retain per-request ownership without global socket patches',async t=>{
 const Native=globalThis.WebSocket,fetchBefore=globalThis.fetch;
 const f=await fixture(t,'success');
 const [a,b]=await Promise.all([f.call('a'),f.call('b')]);
 assert.equal(a.at(-1).reason.kind,'stop');assert.equal(b.at(-1).reason.kind,'stop');
 await f.call('a');
 const sends=f.records().filter(r=>r.type==='transport'&&r.event==='websocket_send');
 assert.equal(sends.length,3);assert.equal(new Set(sends.map(r=>r.connectionId)).size,2);
 assert.equal(sends[2].connectionRequestCount,2);assert.equal(sends[2].connectionReused,true);
 const aId=f.records().find(r=>r.type==='request'&&r.request.sessionId.endsWith('-a')).id;
 assert.equal(sends[2].connectionId,sends.find(r=>r.id===aId).connectionId);
 assert.notEqual(sends[2].id,aId);
 const protocol=f.records().filter(r=>r.type==='transport'&&r.event==='protocol_started');
 assert.deepEqual(new Set(protocol.map(r=>r.id)),new Set(sends.map(r=>r.id)));
 assert.equal(globalThis.WebSocket,Native);
 // The only fetch replacement in this test belongs to the offline endpoint guard.
 assert.notEqual(globalThis.fetch,fetchBefore);
 assert.equal(f.wireMessages.length,3);
 assert.ok(f.wireMessages.every(r=>r.input.some(x=>JSON.stringify(x).includes('PRIVATE_PROMPT'))));
});
test('SSE without Content-Type is identified from fragmented event framing',async t=>{
 const f=await fixture(t,'sse-no-content-type');const chunks=await f.call();
 assert.equal(chunks.at(-1).reason.kind,'stop');
 const end=f.records().find(r=>r.type==='transport'&&r.event==='request_transport_end');
 assert.equal(end.actualTransport,'sse');assert.equal(end.protocolStarted,true);
 assert.equal(end.lastProtocolEvent,'response.completed');assert.ok(end.requestBytes>0);
});
test('compressed SSE remains successful with honestly unavailable protocol observations',async t=>{
 const f=await fixture(t,'sse-gzip');const chunks=await f.call();
 assert.equal(chunks.at(-1).reason.kind,'stop');
 const end=f.records().find(r=>r.type==='transport'&&r.event==='request_transport_end');
 assert.equal(end.actualTransport,'sse');assert.equal(end.protocolStarted,null);
 assert.equal(end.lastProtocolEvent,undefined);
});
test('nested errors are bounded and scrubbed; public snapshots omit error text; observer failure is harmless',()=>{
 const records=[];
 const d=new TransportDiagnostics({record:x=>records.push(x),redact:x=>String(x).replaceAll('QUOTED_SECRET','[REDACTED]')});
 const cause=Object.assign(new Error('Bearer sensitive-token https://user:pass@host/path?token=private'),{code:'ECONNRESET'});
 d.error('socket_error',Object.assign(new Error('QUOTED_SECRET'),{cause,code:'UND_ERR_SOCKET'}));
 assert.ok(!JSON.stringify(records).includes('sensitive-token'));assert.ok(!JSON.stringify(records).includes('user:pass'));
 assert.ok(!JSON.stringify(records).includes('token=private'));assert.ok(!JSON.stringify(records).includes('QUOTED_SECRET'));
 assert.equal(records[0].error.cause.code,'ECONNRESET');
 assert.equal(d.snapshot().errorCode,'UND_ERR_SOCKET');assert.equal(d.snapshot().protocolStarted,null);
 assert.ok(!JSON.stringify(d.snapshot()).includes('message'));
 const broken=new TransportDiagnostics({record:()=>{throw Error('disk unavailable')}});
 assert.doesNotThrow(()=>broken.finish());assert.equal(broken.snapshot().auditWriteFailed,true);
});
