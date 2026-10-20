import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

test('offline replay catches silence before any chunk, selects the earliest timeout, and verifies historical inputs',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'replay-test-'));
 try{
  const logs=path.join(dir,'trials','launch');fs.mkdirSync(logs,{recursive:true});
  const row=(ms,type,id,extra={})=>({time:new Date(ms).toISOString(),type,id,...extra});
  const records=[row(0,'request','normal'),row(100,'chunk','normal',{chunk:{type:'text-delta',text:'hello'}}),row(200,'settled','normal',{usage:{totalTokens:3},finish:{kind:'stop'}}),
   row(1000,'request','silent'),row(701000,'settled','silent',{usage:null,finish:null})];
  const file=path.join(logs,'gateway-audit.jsonl');fs.writeFileSync(file,records.map(JSON.stringify).join('\n')+'\n');
  const output=path.join(dir,'replay.json'),rerun=path.join(dir,'second.json'),script=fileURLToPath(new URL('../../scripts/replay-model-streams.mjs',import.meta.url));
  execFileSync(process.execPath,[script,dir,output]);const d=JSON.parse(fs.readFileSync(output));
  assert.equal(d.completedRequests,1);assert.equal(d.completedRequestsFlagged.length,0);assert.equal(d.flagged[0].failure.code,'stream_idle_timeout');assert.equal(d.flagged[0].wouldStopAfterSeconds,180);
  execFileSync(process.execPath,[script,dir,rerun,output]);fs.appendFileSync(file,'\n');
  assert.throws(()=>execFileSync(process.execPath,[script,dir,rerun,output],{stdio:'pipe'}),/Historical input changed/);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
