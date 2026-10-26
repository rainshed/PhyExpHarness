import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {operations,validateInput} from '../../packages/meta-harness/domain-tools.mjs';
import {validateNativeComposition,nativeEntries,presets} from '../../packages/meta-harness/composition-native.mjs';
import {MetaOutputs} from '../../src/control/meta_outputs.mjs';
import {MetaHost} from '../../src/control/meta_host.mjs';

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
test('current completion tool requires only a reason, summary and write identity',()=>{
 const input={reason:'Comparison finished',summary:'Both approaches failed; results documented.',idempotencyKey:'finish'};
 validateInput('campaign_finish',input);
 for(const name of ['reason','summary']){
  assert.throws(()=>validateInput('campaign_finish',{...input,[name]:' \n '}),/Invalid/);
  const missing={...input};delete missing[name];assert.throws(()=>validateInput('campaign_finish',missing),/Invalid/);
 }
 assert.throws(()=>validateInput('campaign_finish',{...input,condition:'stable'}),/Invalid/);
 const source=JSON.parse(fs.readFileSync(new URL('../../packages/meta-harness/composition-native.json',import.meta.url)));
 const main=nativeEntries(source,{systemPrompt:'fixture'}).find(e=>e.id==='active-meta-preset').config.plugins;
 assert.ok(!main.some(e=>e.id==='meta-stop-review'));
});
test('an explicitly configured legacy composition advertises the new closeout contract',async()=>{
 const {apply}=await import('../../packages/meta-harness/actions.mjs');const registered=[];const calls=[];
 apply({tools:{register:t=>registered.push(t)},metaControl:{observe:async()=>{},call:async(...args)=>{calls.push(args);return {state:'closing'};}}},{closeoutPolicy:'meta-closeout-v1'});
 const tool=registered.find(t=>t.name==='campaign_finish');
 assert.match(tool.description,/reason,summary,idempotencyKey/);assert.doesNotMatch(tool.description,/independent read-only reviewer/);
 const input={reason:'已完成比较',summary:'结果存在局限',idempotencyKey:'finish'};
 await tool.execute({input:JSON.stringify(input)},{});assert.deepEqual(calls[0].slice(0,2),['campaign_finish',input]);
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
test('research uses native continuation and scoped tools; isolated adapter only admits review',async()=>{
 const source=JSON.parse(fs.readFileSync(new URL('../../packages/meta-harness/composition-native.json',import.meta.url)));
 const entries=nativeEntries(source,{role:'meta',systemPrompt:'fixture'});
 assert.ok(entries.some(e=>e.name==='@deepseek-ai/dsh-subagent-spawn-in-process'));
 const main=entries.find(e=>e.id==='active-meta-preset').config.plugins;
 assert.equal(main.find(e=>e.name==='@deepseek-ai/dsh-tool-subagent').config.provider,'spawn');
 assert.ok(main.some(e=>e.name==='@deepseek-ai/dsh-tool-subagent-control/list-agents'));
 const research=entries.find(e=>e.id==='research-declaration').config.plugins;
 assert.ok(research.some(e=>e.name==='@deepseek-ai/dsh-tool-subagent-control'));
 assert.ok(research.some(e=>e.id==='meta-evidence'));
 assert.ok(!research.some(e=>e.id==='meta-experiments'||e.id==='meta-stop-review'));
 let provider;const {apply}=await import('../../packages/meta-harness/isolated-subagent.mjs');
 apply({subagents:{registerProvider:p=>provider=p}});
 await assert.rejects(provider.start({agentPreset:presets.research}),/only supports stop review/);
 const reviewer=nativeEntries(source,{role:'reviewer',reviewerPrompt:'fixture'});
 assert.ok(!reviewer.some(e=>e.name==='@deepseek-ai/dsh-subagent-spawn-in-process'));
});
test('host registers native children in the research boundary and preserves actor attribution',async()=>{
 const calls=[];const host=new MetaHost({config:{id:'attempt'},api:async(_route,body)=>{calls.push(body);return {ok:true};}});
 const binding={id:'main',role:'meta',agents:new Map()};
 const send=async(action,input)=>{let last;for await(const value of host.handle(binding,'meta',{action,input}))last=value;return last;};
 await send('register',{agentId:'main',preset:presets.meta});
 await send('register',{agentId:'child',parentAgentId:'main',preset:presets.research});
 await send('call',{agentId:'child',operation:'campaign_status',input:{}});
 assert.equal(calls.at(-1).input.agentId,'child');
 assert.equal(calls[1].input.runnerId,'main');assert.equal(calls[1].input.isolationScope,'activity-research');
 await assert.rejects(send('call',{agentId:'child',operation:'batch_submit'}),/Read-only/);
 await assert.rejects(send('call',{agentId:'unknown',operation:'campaign_status'}),/Unregistered/);
 await assert.rejects(send('register',{agentId:'forged',preset:presets.reviewer}),/identity mismatch/);
 await assert.rejects(send('register',{agentId:'other',parentAgentId:'foreign',preset:presets.research}),/parent identity mismatch/);
 await assert.rejects(send('register',{agentId:'child',preset:presets.meta}),/identity mismatch/);
 await assert.rejects(send('child_start',{preset:presets.research,prompt:'research'}),/Unsupported child preset/);
});
test('native registered report parameters expose complete nested schema and enforce exclusive inputs',async()=>{
 const {apply}=await import('../../packages/meta-harness/domain-reporting.mjs');const tools=[];
 apply({tools:{register:t=>tools.push(t)},systemPrompt:{section(){}},metaControl:{}},{pluginId:'meta-reporting'});
 const report=tools.find(t=>t.name==='report_save');const schema=report.parameters.properties.analysis;
 assert.deepEqual(schema.required,['summary','observations','hypotheses','limitations','decision','evidenceRefs','brief','researchRefs']);
 assert.deepEqual(schema.properties.problems.items.required,['status','description']);
 assert.deepEqual(schema.properties.problems.items.properties.status.enum,['resolved','unresolved']);
 assert.equal(schema.additionalProperties,false);
 const analysis={brief:'简短结论',researchRefs:[],summary:'ok',observations:[],hypotheses:[],limitations:[],decision:'ok',evidenceRefs:[]};
 const input={factsId:'a'.repeat(64),expectedReportRevision:0,idempotencyKey:'key',analysis};
 validateInput('report_save',input);
 assert.throws(()=>validateInput('report_save',{...input,analysisFile:{path:'/work/analysis/a.json',sha256:'a'.repeat(64)}}));
 assert.throws(()=>validateInput('report_save',{...input,analysis:{brief:'简短结论',researchRefs:[],summary:'only',problems:{}}}));
 assert.throws(()=>validateInput('report_save',{...input,analysis:{...analysis,title:'silently discarded before'}}));
});
test('receipt rendering preserves complete JSON and refuses oversized responses',async()=>{
 const {renderResult}=await import('../../packages/meta-harness/domain-tools.mjs');
 const receipt={receiptVersion:'meta-tool-receipt-v1',status:'completed',summary:'完整',file:{ref:'fixture',path:'/materials/objects/a.json',mediaType:'application/json',bytes:1,sha256:'a'.repeat(64),completeness:'complete'}};
 assert.deepEqual(JSON.parse(renderResult(receipt)[0].text),receipt);
 assert.throws(()=>renderResult({...receipt,summary:'大'.repeat(4096)}));
 assert.ok(Buffer.byteLength(renderResult({text:'native output'.repeat(10000)})[0].text)<4096);
});
