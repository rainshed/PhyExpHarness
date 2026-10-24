import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {spawnSync} from 'node:child_process';
import {appendLog,readLogSync,readLogChunksSync,readLogLinesSync,forgetLog} from '../../src/execution/host/log_store.mjs';
import {createHash} from 'node:crypto';
function fixture(t){const root=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-log-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));return path.join(root,'audit.jsonl');}
test('segments preserve full Unicode bytes across reopen and Python accounting reader',t=>{
 const f=fixture(t),chunks=Array.from({length:30},(_,i)=>JSON.stringify({type:'settled',id:i,text:'科学🧪'.repeat(100)})+'\n');
 for(const c of chunks)appendLog(f,c,{segmentBytes:1700});forgetLog(f);appendLog(f,'tail\n');
 assert.equal(readLogSync(f).toString(),chunks.join('')+'tail\n');
 const p=spawnSync('python3',['-c','from src.execution.host.log_store import read_log; import sys;sys.stdout.buffer.write(read_log(sys.argv[1]))',f]);assert.equal(p.status,0,p.stderr.toString());assert.deepEqual(p.stdout,readLogSync(f));
});
test('pending rotation after manifest publication never duplicates tail',t=>{
 const f=fixture(t);appendLog(f,'completed\n',{segmentBytes:1});const idx=f+'.segments/index.json',m=JSON.parse(fs.readFileSync(idx));m.pending={bytes:m.segments[0].bytes,sha256:m.segments[0].sha256};fs.writeFileSync(idx,JSON.stringify(m));fs.writeFileSync(f,'completed\n');forgetLog(f);
 assert.equal(readLogSync(f).toString(),'completed\n');appendLog(f,'new\n');assert.equal(readLogSync(f).toString(),'completed\nnew\n');
});
test('damaged segment is reported and capacity never silently drops captured bytes',t=>{
 const f=fixture(t);appendLog(f,'abc',{segmentBytes:1,maxBytes:3});assert.throws(()=>appendLog(f,'d',{maxBytes:3}),/capacity/);assert.equal(readLogSync(f).toString(),'abc');fs.writeFileSync(f+'.segments/00000000.gz','broken');assert.throws(()=>readLogSync(f),/damaged/);
});
test('file paging reads compressed segments and complete managed output with original digest',async t=>{
 const {readToolFile}=await import('../../src/control/meta_file_read.mjs');const f=fixture(t);const root=path.dirname(f);fs.mkdirSync(path.join(root,'materials'));const file=path.join(root,'materials','a.log');
 appendLog(file,'甲🧪乙\n',{segmentBytes:1});appendLog(file,'尾');
 const page=await readToolFile(root,root,{path:'/materials/a.log',offset:1,limit:3});assert.equal(page.text,'🧪乙\n');assert.equal(page.total,5);
 const zipped=await readToolFile(root,root,{path:'/materials/a.log.segments/00000000.gz',offset:0,limit:10});assert.equal(zipped.text,'甲🧪乙\n');assert.equal(zipped.storageEncoding,'gzip');
});
test('cumulative audit continues past 256 MiB across reopen and both streaming readers agree',t=>{
 const f=fixture(t),chunk=Buffer.alloc(8*1024*1024,97),digest=createHash('sha256');
 for(let i=0;i<33;i++){appendLog(f,chunk);digest.update(chunk);if(i===31)forgetLog(f);}
 const marker=Buffer.from('\ncomplete 科学🧪\n');appendLog(f,marker);digest.update(marker);
 const expected=33*chunk.length+marker.length,hash=digest.digest('hex');let size=0;const actual=createHash('sha256');
 for(const bytes of readLogChunksSync(f)){size+=bytes.length;actual.update(bytes);assert.ok(bytes.length<=chunk.length);}
 assert.ok(size>256*1024*1024);assert.equal(size,expected);assert.equal(actual.digest('hex'),hash);
 const p=spawnSync('python3',['-c',"from src.execution.host.log_store import iter_log; import hashlib,json,sys; h=hashlib.sha256(); n=0\nfor b in iter_log(sys.argv[1]): h.update(b); n+=len(b)\nprint(json.dumps([n,h.hexdigest()]))",f],{encoding:'utf8'});
 assert.equal(p.status,0,p.stderr);assert.deepEqual(JSON.parse(p.stdout),[expected,hash]);
});
test('streaming snapshot is stable when a writer rotates after reading begins',t=>{
 const f=fixture(t);appendLog(f,'first\n',{segmentBytes:1});appendLog(f,'tail\n');
 const reader=readLogChunksSync(f);assert.equal(reader.next().value.toString(),'first\n');
 appendLog(f,'new\n',{segmentBytes:1});
 assert.equal(Buffer.concat([...reader]).toString(),'tail\n');
 assert.equal(readLogSync(f).toString(),'first\ntail\nnew\n');
});
test('line iteration and file pages preserve Unicode split inside compressed segments',async t=>{
 const f=fixture(t),root=path.dirname(f);fs.mkdirSync(path.join(root,'materials'));const file=path.join(root,'materials','split.log');
 const text='甲🧪乙\nnext\n',bytes=Buffer.from(text);
 for(let i=0;i<bytes.length;i++)appendLog(file,bytes.subarray(i,i+1),{segmentBytes:1});
 assert.deepEqual([...readLogLinesSync(file)],['甲🧪乙','next']);
 const {readToolFile}=await import('../../src/control/meta_file_read.mjs');const page=await readToolFile(root,root,{path:'/materials/split.log',offset:1,limit:3});
 assert.equal(page.text,'🧪乙\n');assert.equal(page.sha256,createHash('sha256').update(bytes).digest('hex'));
 const p=spawnSync('python3',['-c','from src.execution.host.log_store import iter_log_lines; import json,sys; print(json.dumps(list(iter_log_lines(sys.argv[1]))))',file],{encoding:'utf8'});
 assert.equal(p.status,0,p.stderr);assert.deepEqual(JSON.parse(p.stdout),['甲🧪乙','next']);
});
test('explicit output cap, individual record bound and actual disk pressure retain distinct causes',t=>{
 const f=fixture(t);appendLog(f,'abc');
 for(const [options,code] of [[{maxBytes:3},'log_size_limit'],[{maxRecordBytes:1},'log_record_size_limit']]){
  assert.throws(()=>appendLog(f,'xx',options),e=>e.hostFailure.code===code&&e.hostFailure.observed.writtenBytes===3);
 }
 t.mock.method(fs,'statfsSync',()=>({bavail:0,bsize:4096}));
 assert.throws(()=>appendLog(f,'xx'),e=>e.hostFailure.code==='storage_capacity'&&e.hostFailure.observed.freeBytes===0);
 assert.equal(readLogSync(f).toString(),'abc');
});
