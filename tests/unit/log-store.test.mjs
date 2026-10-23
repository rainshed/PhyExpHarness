import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {spawnSync} from 'node:child_process';
import {appendLog,readLogSync,forgetLog} from '../../src/execution/host/log_store.mjs';
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
