import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {nativeEntries,validateNativeComposition} from '../../packages/meta-harness/composition-native.mjs';
const base=JSON.parse(fs.readFileSync(new URL('../../packages/meta-harness/composition-native.json',import.meta.url)));
const descriptor=axis=>({id:`meta-${axis}-reference`,package:`meta-${axis}-reference`,module:'index.mjs',roles:['meta'],enabled:true,config:{},requires:['tools','metaControl']});
for(const axes of [[],['model'],['harness'],['model','harness']])test(`reference capability composition ${axes.join('+')||'none'} is independently scoped`,()=>{
 const composition={...base,plugins:[...base.plugins,...axes.map(descriptor)]};
 validateNativeComposition(composition);
 const entries=nativeEntries(composition,{role:'meta',systemPrompt:'Fixture'});
 const main=entries.find(e=>e.id==='active-meta-preset').config.plugins;
 const child=entries.find(e=>e.id==='research-declaration').config.plugins;
 assert.deepEqual(main.filter(p=>p.id.endsWith('-reference')).map(p=>p.id),axes.map(a=>`meta-${a}-reference`));
 assert.ok(main.filter(p=>p.id.endsWith('-reference')).every(p=>p.name.startsWith('/opt/phyexp/optional-plugins/')));
 assert.equal(child.filter(p=>p.id.endsWith('-reference')).length,0);
 const review=nativeEntries(composition,{role:'reviewer'}).find(e=>e.id==='active-meta-preset').config.plugins;
 assert.equal(review.filter(p=>p.id.endsWith('-reference')).length,0);
});
for(const axis of ['model','harness'])test(`${axis} reference validates input before dispatch and has no peer dependency`,async()=>{
 const plugin=await import(`../../packages/meta-${axis}-reference/index.mjs`);
 const registered=[];const calls=[];
 const ctx={tools:{register:t=>registered.push(t)},metaControl:{observe:async()=>{},call:async(...a)=>{calls.push(a);return {status:'accepted'};}}};
 plugin.apply(ctx,{observeOnly:true});assert.equal(registered.length,0);
 plugin.apply(ctx);assert.equal(registered.length,4);
 const submit=registered.find(t=>t.name.endsWith('_submit'));
 await assert.rejects(()=>submit.execute({provider:'forged'},{}),/missing required/);assert.equal(calls.length,0);
 const input={tasks:['task'],repeats:1,researchQuestion:'Compare tool recovery',idempotencyKey:'once',expectedPolicyRevision:1,...(axis==='model'?{candidateId:'candidate',modelRef:'model'}:{harnessRef:'codex',modelRef:'approved'})};
 assert.equal((await submit.execute(input,{})).status,'accepted');assert.deepEqual(calls[0].slice(0,2),[submit.name,input]);
 assert.equal((await submit.execute({...input,repeats:0},{})).error.code,'invalid_input');
 assert.equal((await submit.execute({...input,modelRef:'arbitrary',apiKey:'secret'},{})).error.code,'invalid_input');
 const pkg=JSON.parse(fs.readFileSync(new URL(`../../packages/meta-${axis}-reference/package.json`,import.meta.url)));
 assert.ok(!Object.keys(pkg.dependencies).some(d=>d.includes('meta-')));
});
test('optional entries cannot masquerade as core plugins or register in child roles',()=>{
 for(const change of [{package:'../../evil'}, {module:'../index.mjs'}, {roles:['research']}, {id:'meta-experiments'}, {package:undefined}]) {
  assert.throws(()=>validateNativeComposition({...base,plugins:[...base.plugins,{...descriptor('model'),...change}]}));
 }
});
