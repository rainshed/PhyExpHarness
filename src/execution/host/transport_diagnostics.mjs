import crypto from 'node:crypto';
import {AsyncLocalStorage} from 'node:async_hooks';
import {channel} from 'node:diagnostics_channel';

// Host-only observations. Do not change transport selection, retry, cancellation,
// or stream contents. Node's channels expose events before adapter normalization.
const scope=new AsyncLocalStorage(),httpRequests=new WeakMap();
let installed=false;
const MAX_LINE=16384;
const name=value=>typeof value==='string'&&/^[\w.-]{1,80}$/.test(value)?value:undefined;
const protocolName=value=>typeof value==='string'&&/^(response\.[a-z_.]+|codex\.(rate_limits|response\.metadata)|message_(start|delta|stop)|content_block_(start|delta|stop)|ping|error)$/.test(value)?value:undefined;
const bytes=value=>typeof value==='string'?Buffer.byteLength(value):value?.byteLength??value?.size??0;
function safeText(value,redact) {
 return redact(String(value))
  .replace(/\b(?:Bearer|Basic)\s+[^\s"',;]+/gi,'[REDACTED]')
  .replace(/https?:\/\/[^\s"'<>]+/g,raw=>{try{const u=new URL(raw);u.username='';u.password='';u.search='';u.hash='';return u.href}catch{return '[URL]'}})
  .replace(/((?:api[-_]?key|access_token|refresh_token|authorization)\s*[:=]\s*)[^\s,;]+/gi,'$1[REDACTED]')
  .slice(0,1000);
}
function errorFacts(error,redact,depth=0) {
 if(!error||depth>3)return undefined;
 const result={name:name(error.name&&safeText(error.name,redact)),code:name(error.code&&safeText(error.code,redact))};
 if(typeof error.message==='string')result.message=safeText(error.message,redact);
 if(error.cause&&error.cause!==error)result.cause=errorFacts(error.cause,redact,depth+1);
 return result;
}
function header(headers,key) {
 // Undici emits a flat Buffer/string array. Never persist the header collection.
 if(!Array.isArray(headers))return '';
 for(let i=0;i+1<headers.length;i+=2)if(String(headers[i]).toLowerCase()===key)return String(headers[i+1]);
 return '';
}
function eventType(text) {
 // Only retain the event type, never response text, tool arguments or payloads.
 if(text.length>MAX_LINE)return protocolName(text.match(/^\s*\{\s*"type"\s*:\s*"([^"]+)"/)?.[1]);
 try{return protocolName(JSON.parse(text)?.type)}catch{return undefined}
}
function observe(callback) {
 // Telemetry must never throw into a socket callback or change a request outcome.
 return value=>{try{callback(value)}catch{}};
}
function install() {
 if(installed)return;installed=true;
 channel('undici:request:create').subscribe(observe(({request})=>{
  const owner=scope.getStore();if(!owner)return;
  const attempt={owner,requestBytes:0,responseBytes:0,decoder:new TextDecoder(),buffer:'',discardLine:false};
  owner.data.httpRequestCount=(owner.data.httpRequestCount||0)+1;
  owner.lastTransportAttempt='http';
  httpRequests.set(request,attempt);
  owner.emit('http_request',{method:['GET','POST'].includes(request.method)?request.method:'other'});
 }));
 channel('undici:request:bodyChunkSent').subscribe(observe(({request,chunk})=>{
  const attempt=httpRequests.get(request);if(attempt)attempt.requestBytes+=bytes(chunk);
 }));
 channel('undici:request:headers').subscribe(observe(({request,response})=>{
  const attempt=httpRequests.get(request);if(!attempt)return;
  const type=header(response.headers,'content-type'),encoding=header(response.headers,'content-encoding');
  attempt.sse=type.includes('text/event-stream');
  // Some real streaming endpoints omit Content-Type. Confirm those streams
  // from their data: JSON event framing, without guessing from configuration.
  attempt.parse=(attempt.sse||!type)&&(!encoding||encoding==='identity');
  const owner=attempt.owner;
  if(attempt.sse) {
   if(owner.data.actualTransport==='websocket')owner.data.fallbackToSse=true;
   owner.data.actualTransport='sse';
   owner.data.protocolStarted??=attempt.parse?false:null;
  }else owner.data.actualTransport??='http';
  owner.data.httpStatus=response.statusCode;
  const retryAfter=header(response.headers,'retry-after').trim();
  const delay=/^\d+(?:\.\d+)?$/.test(retryAfter)?Number(retryAfter)*1000:Date.parse(retryAfter)-Date.now();
  owner.httpFailureFacts={status:response.statusCode,
   ...(Number.isFinite(delay)&&delay>0?{providerRetryAfterMs:delay}:{})};
  owner.data.requestBytes=attempt.requestBytes;
  owner.emit('http_response',{status:response.statusCode,transport:attempt.sse?'sse':'http',
   requestBytes:attempt.requestBytes,sseEventsObservable:attempt.parse});
 }));
 channel('undici:request:bodyChunkReceived').subscribe(observe(({request,chunk})=>{
  const attempt=httpRequests.get(request);if(!attempt)return;
  attempt.responseBytes+=bytes(chunk);
  attempt.owner.data.receivedBodyBytes=attempt.responseBytes;
  if(!attempt.parse)return;
  // Bound the scratch buffer independently of request execution limits.
  const text=attempt.decoder.decode(chunk,{stream:true});
  for(const part of text.match(/[^\n]*\n|[^\n]+$/g)||[]) {
   const newline=part.endsWith('\n');
   if(!attempt.discardLine) {
    const room=MAX_LINE-attempt.buffer.length;
    attempt.buffer+=part.slice(0,room);
    if(newline||part.length>room) {
     const line=attempt.buffer.trim();
     if(line.startsWith('data:')) {
      const type=eventType(line.slice(5).trim());
      if(type) {
       if(attempt.owner.data.actualTransport==='websocket')attempt.owner.data.fallbackToSse=true;
       attempt.owner.data.actualTransport='sse';
       attempt.owner.protocol(type,'sse');
      }
     }
     attempt.buffer='';attempt.discardLine=!newline;
    }
   }else if(newline)attempt.discardLine=false;
  }
 }));
 channel('undici:request:error').subscribe(observe(({request,error})=>{
  httpRequests.get(request)?.owner.error('http_error',error);
 }));
 channel('undici:websocket:open').subscribe(observe(({websocket})=>{
  const owner=scope.getStore();if(!owner)return;
  const connection={id:crypto.randomUUID(),openedAt:Date.now(),requests:0,owner,closed:false};
  owner.connections.add(connection);
  owner.data.actualTransport='websocket';
  owner.emit('websocket_open',{connectionId:connection.id});
  const original=websocket.send,own=Object.getOwnPropertyDescriptor(websocket,'send');
  const send=function(data) {
   // Async contexts on reused sockets still belong to the first request.
   // Bind each send to its current request rather than that stale context.
   try{const current=scope.getStore();
   if(current) {
    if(connection.owner!==owner)connection.owner.connections.delete(connection);
    connection.owner=current;connection.requests++;
    current.connections.add(connection);
    current.data.actualTransport='websocket';
    current.lastTransportAttempt='websocket';
    current.data.protocolStarted=false;
    current.data.connectionId=connection.id;
    current.data.connectionAgeMs=Date.now()-connection.openedAt;
    current.data.connectionRequestCount=connection.requests;
    current.data.connectionReused=connection.requests>1;
    current.data.requestBytes=bytes(data);
    current.emit('websocket_send',{...current.connectionFacts(connection),requestBytes:bytes(data)});
   }}catch{}
   return original.call(this,data);
  };
  websocket.send=send;
  const onMessage=observe(event=>{
   const current=connection.owner;
   current.data.receivedBodyBytes=(current.data.receivedBodyBytes||0)+bytes(event.data);
   if(typeof event.data==='string')current.protocol(eventType(event.data),'websocket');
  });
  const onError=observe(event=>connection.owner.error('websocket_error',event.error||event,connection));
  const onClose=observe(event=>{
   connection.closed=true;const current=connection.owner;
   current.data.closeCode=event.code;current.data.wasClean=event.wasClean;
   current.emit('websocket_close',{...current.connectionFacts(connection),closeCode:event.code,
    wasClean:event.wasClean,closeReason:safeText(event.reason,current.redact)});
   websocket.removeEventListener('message',onMessage);
   websocket.removeEventListener('error',onError);
   websocket.removeEventListener('close',onClose);
   if(websocket.send===send){if(own)Object.defineProperty(websocket,'send',own);else delete websocket.send;}
   // Release all observer references from the context retained by the socket.
   owner.connections.delete(connection);current.connections.delete(connection);
  });
  websocket.addEventListener('message',onMessage);
  websocket.addEventListener('error',onError);
  websocket.addEventListener('close',onClose);
 }));
 channel('undici:websocket:socket_error').subscribe(observe(error=>{
  // Node publishes only an Error here, not a socket identity. Attribute only
  // when the originating context owns exactly one live observed connection.
  const candidates=[...(scope.getStore()?.connections||[])].filter(c=>!c.closed);
  if(candidates.length===1)candidates[0].owner.error('socket_error',error,candidates[0]);
 }));
}

export class TransportDiagnostics {
 constructor({record,redact=String,configuredTransport}){
  install();this.record=record;this.redact=redact;this.connections=new Set();this.startedAt=Date.now();
  this.data={version:'model-transport-v1',observer:'node-undici',configuredTransport:configuredTransport||'provider-default',
   actualTransport:null,protocolStarted:null,receivedBodyBytes:0};
  this.ended=false;
 }
 run(callback){return scope.run(this,callback);}
 connectionFacts(connection){return {connectionId:connection.id,connectionAgeMs:Date.now()-connection.openedAt,
  connectionRequestCount:connection.requests,connectionReused:connection.requests>1};}
 emit(event,details={}){
  try{this.record({event,...details,elapsedMs:Date.now()-this.startedAt,afterRequestEnd:this.ended});}catch{
   this.data.auditWriteFailed=true;
  }
 }
 protocol(type,transport){
  if(!type)return;
  this.data.protocolEventCount=(this.data.protocolEventCount||0)+1;
  this.data.lastProtocolEvent=type;
  this.data.firstProtocolEvent??=type;
  if(type.startsWith('response.')||type==='message_start'){
   if(this.data.protocolStarted!==true){
    this.data.protocolStarted=true;this.data.protocolStartedAfterMs=Date.now()-this.startedAt;
    this.emit('protocol_started',{transport,eventType:type});
   }
  }
  if(['response.completed','response.failed','response.incomplete','error','message_stop'].includes(type))
   this.emit('protocol_terminal',{transport,eventType:type});
 }
 error(event,error,connection){
  const facts=errorFacts(error,this.redact);
  if(facts?.code&&/^(E[A-Z0-9_]{2,40}|UND_ERR_[A-Z_]+|WS_ERR_[A-Z_]+|TRANSPORT|SERVER|TIMEOUT|PI_AI_ERROR)$/.test(facts.code))
   this.data.errorCode=facts.code;
  this.emit(event,{...(connection?this.connectionFacts(connection):{}),error:facts});
 }
 adapterFailure(failure){
  this.emit('adapter_failure',{error:errorFacts(failure,this.redact)});
 }
 failureFacts(){
  // Only a single HTTP attempt in this logical request is unambiguous. Do not
  // borrow status from another request, an auth/redirect chain, or an earlier
  // HTTP request followed by WebSocket generation.
  return this.data.httpRequestCount===1&&this.lastTransportAttempt==='http'&&this.httpFailureFacts?.status>=400
   ?{...this.httpFailureFacts}:{};
 }
 snapshot(){
  const value={...this.data};
  // Errors/close reasons stay in the sanitized audit; public summaries contain facts.
  return value;
 }
 finish(){this.ended=true;this.emit('request_transport_end',this.snapshot());}
}
