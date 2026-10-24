import {Readable} from 'node:stream';
import {readLogChunksSync} from '../src/execution/host/log_store.mjs';
// Offline only: replay recorded timestamps/chunks; no provider, credentials or containers.
import fs from 'node:fs';import crypto from 'node:crypto';import path from 'node:path';import readline from 'node:readline';
import {StreamGuard,DEFAULT_STREAM_POLICY} from '../src/execution/host/stream_guard.mjs';
const [data,output,priorReplay]=process.argv.slice(2);if(!data||!output)throw new Error('Usage: node scripts/replay-model-streams.mjs DATA_DIR OUTPUT_JSON [PRIOR_REPLAY_JSON]');
const files=[];
const expectedHashes=priorReplay?JSON.parse(fs.readFileSync(priorReplay,'utf8')).inputHashes:null;
if(expectedHashes){for(const relative of Object.keys(expectedHashes)){
 const file=path.resolve(data,relative);if(!file.startsWith(path.resolve(data)+path.sep))throw new Error('Replay path outside data directory');files.push(file);
}}
else for(const branch of ['trials','campaigns']){
 const base=path.join(data,branch);if(!fs.existsSync(base))continue;
 for(const item of fs.readdirSync(base,{recursive:true}))if(item.endsWith('gateway-audit.jsonl'))files.push(path.join(base,item));
}
const requests=[],inputHashes={};
function timeFault(v,now){
 const idleAt=(v.last??v.start)+DEFAULT_STREAM_POLICY.streamIdleTimeoutMs,requestAt=v.start+DEFAULT_STREAM_POLICY.requestTimeoutMs;
 const at=Math.min(idleAt,requestAt);return now>=at?v.guard.fault(idleAt<requestAt?'stream_idle_timeout':'request_timeout',at):null;
}
for(const file of files){
 const active=new Map(),hash=crypto.createHash('sha256'),input=Readable.from(readLogChunksSync(file));input.on('data',chunk=>hash.update(chunk));
 for await(const line of readline.createInterface({input,crlfDelay:Infinity})){
  let r;try{r=JSON.parse(line);}catch{continue;}const now=Date.parse(r.time);
  if(r.type==='request'){active.set(r.id,{id:r.id,file:path.relative(data,file),start:now,last:null,guard:new StreamGuard(DEFAULT_STREAM_POLICY,now),chunks:0});continue;}
  const v=active.get(r.id);if(!v)continue;
  if(r.type==='chunk'){
   if(!v.failure){
    v.failure=timeFault(v,now)||v.guard.accept(r.chunk,now);
    if(v.failure)v.wouldStopAfterSeconds=(Date.parse(v.failure.detectedAt)-v.start)/1000;
   }
   v.chunks++;v.last=now;if(r.chunk.type==='finish')v.finish=r.chunk.reason;
  }
  if(r.type==='settled'){
   if(!v.failure)v.failure=timeFault(v,now);
   if(v.failure)v.wouldStopAfterSeconds=(Date.parse(v.failure.detectedAt)-v.start)/1000;
   v.originalSeconds=(now-v.start)/1000;v.originalUsage=r.usage;v.originalFinish=r.finish;
   v.responseBytes=v.guard.bytes;v.warningCount=v.guard.warnings.length;
   delete v.guard;requests.push(v);active.delete(r.id);
  }
 }
 inputHashes[path.relative(data,file)]=hash.digest('hex');
 if(expectedHashes&&expectedHashes[path.relative(data,file)]!==inputHashes[path.relative(data,file)])throw new Error('Historical input changed: '+path.relative(data,file));
 for(const v of active.values()){delete v.guard;v.incomplete=true;requests.push(v);}
}
const complete=requests.filter(r=>r.originalFinish&&!['error','max-tokens'].includes(r.originalFinish.kind));
const result={schemaVersion:1,mode:'offline-recorded-timestamps',inputHashes,policy:DEFAULT_STREAM_POLICY,files:files.length,requests:requests.length,
 completedRequests:complete.length,completedRequestsFlagged:complete.filter(r=>r.failure),flagged:requests.filter(r=>r.failure),incomplete:requests.filter(r=>r.incomplete),
 normalMaxResponseBytes:Math.max(0,...complete.map(r=>r.responseBytes||0)),normalMaxRequestSeconds:Math.max(0,...complete.map(r=>r.originalSeconds||0))};
fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify({files:result.files,requests:result.requests,completed:complete.length,completedFlagged:result.completedRequestsFlagged.length,flagged:result.flagged.map(r=>({file:r.file,code:r.failure.code,wouldStopAfterSeconds:r.wouldStopAfterSeconds,originalSeconds:r.originalSeconds})),normalMaxResponseBytes:result.normalMaxResponseBytes,normalMaxRequestSeconds:result.normalMaxRequestSeconds}));
if(result.completedRequestsFlagged.length)process.exitCode=1;
