// One synchronous writer per log. Closed gzip members publish before the tail is cleared.
import fs from 'node:fs';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {gzipSync,gunzipSync} from 'node:zlib';
import {StringDecoder} from 'node:string_decoder';
const hash=b=>createHash('sha256').update(b).digest('hex');
const cache=new Map();
const version='segmented-log-v1';
function indexPath(file){return file+'.segments/index.json';}
function durable(file,bytes){const fd=fs.openSync(file,'w',0o600);try{fs.writeFileSync(fd,bytes);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}}
function save(file,index){const target=indexPath(file);fs.mkdirSync(path.dirname(target),{recursive:true});const temp=target+'.'+randomUUID();durable(temp,JSON.stringify(index)+'\n');fs.renameSync(temp,target);}
function load(file){const index=indexPath(file);if(fs.existsSync(index)&&(fs.lstatSync(path.dirname(index)).isSymbolicLink()||fs.lstatSync(index).isSymbolicLink()||!fs.lstatSync(index).isFile()))throw new Error('Invalid log index path');return fs.existsSync(index)?JSON.parse(fs.readFileSync(index)):{version,segments:[],pending:null};}
function validate(index){if(index.version!==version||!Array.isArray(index.segments))throw new Error('Invalid segmented log');for(const [i,s] of index.segments.entries())if(s.name!==String(i).padStart(8,'0')+'.gz'||!Number.isSafeInteger(s.bytes)||s.bytes<0||s.bytes>256*1024*1024||!/^[a-f0-9]{64}$/.test(s.sha256))throw new Error('Invalid log segment identity');}
function tail(file,index){let data=fs.existsSync(file)?fs.readFileSync(file):Buffer.alloc(0);if(index.pending&&data.length){const n=index.pending.bytes;if(data.length<n||hash(data.subarray(0,n))!==index.pending.sha256)throw new Error('Interrupted log rotation is inconsistent');data=data.subarray(n);}return data;}
function snapshot(file){
 for(let attempt=0;attempt<4;attempt++){
  const index=load(file);validate(index);const revision=JSON.stringify(index);let current;
  try{current=tail(file,index);}catch(error){if(JSON.stringify(load(file))!==revision)continue;throw error;}
  if(JSON.stringify(load(file))===revision)return {index,current};
 }
 throw new Error('Log changed during reading; retry');
}
// Capture the tail before yielding. Published segments are immutable, so later
// appends/rotations cannot duplicate bytes or change this reader's prefix.
export function* readLogChunksSync(file){
 const {index,current}=snapshot(file);
 for(const s of index.segments){const part=path.join(file+'.segments',s.name);if(fs.lstatSync(file+'.segments').isSymbolicLink()||!fs.lstatSync(part).isFile()||fs.lstatSync(part).isSymbolicLink())throw new Error('Invalid log segment path');const compressed=fs.readFileSync(part);if(hash(compressed)!==s.storedSha256)throw new Error('Compressed log segment is damaged');const bytes=gunzipSync(compressed,{maxOutputLength:s.bytes+1});if(bytes.length!==s.bytes||hash(bytes)!==s.sha256)throw new Error('Log content is damaged');yield bytes;}
 yield current;
}
export function* readLogLinesSync(file){
 const decoder=new StringDecoder('utf8');let pending='';
 for(const chunk of readLogChunksSync(file)){
  const lines=(pending+decoder.write(chunk)).split('\n');pending=lines.pop();yield* lines;
 }
 pending+=decoder.end();if(pending)yield pending;
}
export function* readLogRecordsSync(file){for(const line of readLogLinesSync(file))if(line.trim())yield JSON.parse(line);}
// Compatibility for bounded output artifacts; audit consumers use the iterators.
export function readLogSync(file){return Buffer.concat([...readLogChunksSync(file)]);}
function storageError(code,observed,limits){
 return Object.assign(new Error('Storage capacity exceeded; captured log retained'),{code:'STORAGE_CAPACITY',hostFailure:{
  schemaVersion:1,code,stage:'logging',source:'host-log-store',termination:'storage',detectedAt:new Date().toISOString(),observed,limits}});
}
function rotate(file,state){
 const raw=fs.readFileSync(file);const compressed=gzipSync(raw,{level:3});const name=String(state.index.segments.length).padStart(8,'0')+'.gz';
 const folder=file+'.segments';fs.mkdirSync(folder,{recursive:true});const target=path.join(folder,name),temp=target+'.'+randomUUID();
 durable(temp,compressed);fs.renameSync(temp,target);
 const segment={name,bytes:raw.length,sha256:hash(raw),storedSha256:hash(compressed)};
 state.index={version,segments:[...state.index.segments,segment],pending:{bytes:raw.length,sha256:segment.sha256}};save(file,state.index);
 fs.truncateSync(file,0);state.size=0;state.index={...state.index,pending:null};save(file,state.index);
}
export function appendLog(file,value,{segmentBytes=8*1024*1024,maxBytes=Infinity,maxRecordBytes=256*1024*1024,minFreeBytes=64*1024*1024}={}){
 // Cumulative audit growth belongs to activity/global storage admission. Only
 // explicitly bounded artifacts (e.g. tool output) supply a cumulative maxBytes.
 if(!Number.isSafeInteger(segmentBytes)||segmentBytes<1||segmentBytes>256*1024*1024||!Number.isSafeInteger(maxRecordBytes)||maxRecordBytes<1||maxRecordBytes>256*1024*1024||!(maxBytes===Infinity||Number.isSafeInteger(maxBytes)&&maxBytes>=0)||!Number.isSafeInteger(minFreeBytes)||minFreeBytes<0)throw new Error('Invalid log storage limits');
 const data=Buffer.isBuffer(value)?value:Buffer.from(value);let state=cache.get(file);
 try{
 if(!state||state.index.pending||!fs.existsSync(file)){
  const index=load(file);validate(index);
  if(index.pending){const remaining=tail(file,index);fs.writeFileSync(file,remaining);index.pending=null;save(file,index);}
  const size=fs.existsSync(file)?fs.statSync(file).size:0;
  state={index,size,total:index.segments.reduce((n,s)=>n+s.bytes,0)+size};cache.set(file,state);
 }
 const disk=fs.statfsSync(path.dirname(file));
 const observed={log:path.basename(file),writtenBytes:state.total,attemptedBytes:data.length};
 if(data.length>maxRecordBytes)throw storageError('log_record_size_limit',observed,{maxRecordBytes});
 if(state.total+data.length>maxBytes)throw storageError('log_size_limit',observed,{maxBytes});
 if(disk.bavail*disk.bsize<data.length+minFreeBytes)throw storageError('storage_capacity',{...observed,freeBytes:disk.bavail*disk.bsize},{minFreeBytes});
 // A large record owns its segment; never publish a segment beyond the reader's bound.
 if(state.size&&state.size+data.length>segmentBytes)rotate(file,state);
 fs.appendFileSync(file,data);state.size+=data.length;state.total+=data.length;
 if(state.size>=segmentBytes)rotate(file,state);
 }catch(error){
  cache.delete(file); // A filesystem write may have partially completed.
  if(!error.hostFailure)error.hostFailure={schemaVersion:1,code:['ENOSPC','EDQUOT'].includes(error.code)?'storage_capacity':'storage_write_error',stage:'logging',source:'host-log-store',termination:'storage',detectedAt:new Date().toISOString(),observed:{log:path.basename(file),...(error.code?{errorCode:error.code}:{})}};
  throw error;
 }
}
export function forgetLog(file){cache.delete(file);}
