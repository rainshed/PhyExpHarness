import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {MetaOutputs} from '../../src/control/meta_outputs.mjs';
import {MetaHost} from '../../src/control/meta_host.mjs';
import {readToolFile} from '../../src/control/meta_file_read.mjs';
import {archiveOutput,projectOutput} from '../../packages/meta-harness/output-context.mjs';
const big='完整🧪'.repeat(180000)+'UNIQUE_TAIL';
function fixture(t){const root=fs.mkdtempSync(path.join(os.tmpdir(),'meta-boundary-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));for(const n of ['materials','evidence','sdk','versions','outputs'])fs.mkdirSync(path.join(root,n));return {root,outputs:new MetaOutputs(path.join(root,'outputs'))};}
for(const mode of ['success','error','denial','replacement','contexts'])test('complete native output is archived before compacting '+mode,async t=>{
 const {root,outputs}=fixture(t);const result={content:[{type:'text',text:big}],value:{full:big},isError:mode==='error'};
 const decision=mode==='denial'?{kind:'block',feedback:[{type:'text',text:big}]}:mode==='replacement'?{kind:'accept',value:{full:big}}:mode==='contexts'?{kind:'accept',additionalContexts:[{content:[{type:'text',text:big}]}]}:{kind:'accept'};
 const value={name:'session_event_read',...result,decision};let largest=0;
 const file=await archiveOutput(value,async(action,input)=>{largest=Math.max(largest,Buffer.byteLength(JSON.stringify(input)));if(action==='output_open')return outputs.open(input.id,input.kind);if(action==='output_append')return outputs.append(input.id,input.sequence,input.bytes);return outputs.close(input.id,'complete');});
 assert.ok(largest<100000);assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root,'outputs',file.id+'.log'))),value);
 const projected=projectOutput({name:'session_event_read'},result,decision,file);
 assert.ok(Buffer.byteLength(JSON.stringify(projected))<4096);assert.ok(!JSON.stringify(projected).includes('UNIQUE_TAIL'));
 assert.equal(projected.kind,mode==='error'||mode==='denial'||mode==='contexts'?'block':'accept');
});
test('file pages reach a long single-line Unicode tail and enforce mount ownership',async t=>{
 const {root,outputs}=fixture(t);fs.writeFileSync(path.join(root,'materials','full.json'),big);
 let offset=0,sha256,restored='';
 while(offset!==null){const page=await readToolFile(root,outputs.root,{path:'/materials/full.json',offset,limit:8192,sha256});restored+=page.text;offset=page.nextOffset;sha256=page.sha256;assert.ok(Buffer.byteLength(JSON.stringify(page))<64*1024);}
 assert.equal(restored,big);
 for(const location of ['/work/secret','/materials/../secret','/outputs/../other/secret'])await assert.rejects(readToolFile(root,outputs.root,{path:location}));
 fs.symlinkSync('/etc/passwd',path.join(root,'materials','escape'));await assert.rejects(readToolFile(root,outputs.root,{path:'/materials/escape'}));
 fs.writeFileSync(path.join(root,'materials','full.json'),'changed');await assert.rejects(readToolFile(root,outputs.root,{path:'/materials/full.json',sha256}),/changed/);
 await assert.rejects(readToolFile(root,outputs.root,{path:'/materials/full.json',limit:8193}),/Invalid/);
});
test('review request, denial, approval and replay never embed their snapshots; host errors have full files',async t=>{
 const {root,outputs}=fixture(t);let state='pending',replayed=false;
 const host=new MetaHost({config:{id:'main',filesRoot:root},api:async(_route,{action})=>{if(action==='review_request'||action==='review_status')return {id:'review',state,replayed,snapshot:{full:big},result:{reason:big}};throw new Error(big);}});
 const binding={id:'main',role:'meta',outputs,agents:new Map()};
 const send=async(action,input={})=>{let result;for await(const row of host.handle(binding,'meta',{action,input}))result=row;return result;};
 for(const current of ['pending','rejected','approved','failed']){
  state=current;replayed=current!=='pending';const result=await send(current==='pending'?'review_request':'review_status');
  assert.equal(result.state,state);assert.ok(Buffer.byteLength(JSON.stringify(result))<4096);
  const full=JSON.parse(fs.readFileSync(path.join(root,result.file.path)));assert.equal(full.snapshot.full,big);assert.equal(full.result.reason,big);
 }
 await assert.rejects(send('user_question'),error=>{const result=JSON.parse(error.message);assert.ok(error.message.length<4096);assert.equal(JSON.parse(fs.readFileSync(path.join(outputs.root,result.file.id+'.log'))).error,'Error: '+big);return true;});
});
test('child creation and cleanup failures publish full diagnostics before returning',async t=>{
 const {root}=fixture(t);const host=new MetaHost({config:{id:'main',filesRoot:root},api:async()=>({})});
 host.create=()=>{throw new Error(big);};
 const child={id:'failed-child',role:'reviewer',reviewId:'review'};
 const result=await host.runChild(child,[],{});assert.ok(Buffer.byteLength(JSON.stringify(result))<4096);
 const saved=JSON.parse(fs.readFileSync(path.join(root,'materials','agents',child.id,'index.json')));
 assert.equal(saved.result.diagnostic,'Error: '+big);assert.equal(result.stopReason,'error');
});
