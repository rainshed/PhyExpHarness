import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {operations,validateInput} from '../../packages/meta-harness/domain-tools.mjs';
import {validateNativeComposition} from '../../packages/meta-harness/composition-native.mjs';
import {MetaOutputs} from '../../src/control/meta_outputs.mjs';

for(const domain of ['campaign','experiments','evidence','reporting'])test(`${domain} is independently scoped, with typed native schemas and direct service calls`,async()=>{
 const {apply}=await import(`../../packages/meta-harness/domain-${domain}.mjs`);const tools=[];const calls=[];
 const ctx={tools:{register:t=>tools.push(t)},systemPrompt:{section(){}},metaControl:{observe:async()=>{},call:async(...args)=>{calls.push(args);return {status:'accepted'};}}};
 apply(ctx,{pluginId:'meta-'+domain,text:'Fixture',observeOnly:true});
 assert.deepEqual(tools.map(t=>t.name),Object.keys(operations).filter(n=>operations[n].plugin===domain&&!operations[n].write));
 for(const t of tools){assert.equal(t.parameters.type,'object');assert.ok(!t.parameters.properties.input);}
 if(domain==='campaign'){
  const result=await tools[0].execute({},{agent:{session:{id:'test'}},signal:new AbortController().signal});
  assert.deepEqual(result,{status:'accepted'});assert.equal(calls[0][0],'campaign_status');
 }
});
test('contract rejects string encoded JSON, unknown fields, malformed nested parameters and missing write identity',()=>{
 assert.throws(()=>validateInput('batch_submit',{input:'{}'}),/Invalid/);
 assert.throws(()=>validateInput('batch_submit',{candidateId:'a',tasks:['task'],repeats:1}),/Invalid/);
 assert.throws(()=>validateInput('candidate_freeze',{plugins:[{path:'p',config:3}],description:'test',idempotencyKey:'x'}),/Invalid/);
 assert.throws(()=>validateInput('campaign_status',{role:'reviewer'}),/Invalid/);
});
test('composition validates role dependencies and removing a required domain fails',()=>{
 const source=JSON.parse(fs.readFileSync(new URL('../../packages/meta-harness/composition-native.json',import.meta.url)));
 const missing=structuredClone(source);missing.plugins.find(p=>p.id==='meta-evidence').enabled=false;assert.throws(()=>validateNativeComposition(missing),/Missing complete/);
 const role=structuredClone(source);role.plugins[0].roles=['meta'];assert.throws(()=>validateNativeComposition(role),/scoped/);
 const optional=structuredClone(source);optional.plugins.find(p=>p.id==='meta-stop-review').enabled=false;validateNativeComposition(optional);
});
test('complete and interrupted output survives restart and capacity refuses additional bytes',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'meta-output-test-'));const first=new MetaOutputs(root,{maxBytes:20});
 first.open('one','terminal');first.append('one',0,Buffer.from('完整尾部').toString('base64'));
 const second=new MetaOutputs(root,{maxBytes:20});assert.equal(second.entries.get('one').status,'interrupted');assert.equal(second.entries.get('one').completeness,'partial');
 second.open('two','terminal');assert.throws(()=>second.append('two',0,Buffer.alloc(20).toString('base64')),/capacity/);assert.equal(second.entries.get('two').completeness,'partial');
 assert.equal(fs.readFileSync(path.join(root,'one.log'),'utf8'),'完整尾部');
});
test('native registered report parameters expose complete nested schema and enforce exclusive inputs',async()=>{
 const {apply}=await import('../../packages/meta-harness/domain-reporting.mjs');const tools=[];
 apply({tools:{register:t=>tools.push(t)},systemPrompt:{section(){}},metaControl:{}},{pluginId:'meta-reporting'});
 const report=tools.find(t=>t.name==='report_save');const schema=report.parameters.properties.analysis;
 assert.deepEqual(schema.required,['summary','observations','hypotheses','limitations','decision','evidenceRefs']);
 assert.deepEqual(schema.properties.problems.items.required,['status','description']);
 assert.deepEqual(schema.properties.problems.items.properties.status.enum,['resolved','unresolved']);
 assert.equal(schema.additionalProperties,false);
 const analysis={summary:'ok',observations:[],hypotheses:[],limitations:[],decision:'ok',evidenceRefs:[]};
 const input={factsId:'a'.repeat(64),expectedReportRevision:0,idempotencyKey:'key',analysis};
 validateInput('report_save',input);
 assert.throws(()=>validateInput('report_save',{...input,analysisFile:{path:'/work/analysis/a.json',sha256:'a'.repeat(64)}}));
 assert.throws(()=>validateInput('report_save',{...input,analysis:{summary:'only',problems:{}}}));
 assert.throws(()=>validateInput('report_save',{...input,analysis:{...analysis,title:'silently discarded before'}}));
});
test('receipt rendering preserves complete JSON and refuses oversized responses',async()=>{
 const {renderResult}=await import('../../packages/meta-harness/domain-tools.mjs');
 const receipt={receiptVersion:'meta-tool-receipt-v1',status:'completed',summary:'完整',file:{ref:'fixture',path:'/materials/objects/a.json',mediaType:'application/json',bytes:1,sha256:'a'.repeat(64),completeness:'complete'}};
 assert.deepEqual(JSON.parse(renderResult(receipt)[0].text),receipt);
 assert.throws(()=>renderResult({...receipt,summary:'大'.repeat(4096)}));
 assert.equal(JSON.parse(renderResult({text:'native output'.repeat(4096)})[0].text).text.length,53248);
});
