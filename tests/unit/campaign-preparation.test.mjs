import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {build} from 'esbuild';
import {campaignPreparation} from '../../packages/meta-workbench-studio/client/components/campaign-preparation.mjs';

const fixture=()=>({state:'draft',config:{referencePolicy:{harnessEnabled:true,harnessRefs:['codex','dsh-standard']},
 referenceBindings:{harnesses:{codex:{name:'Codex'},'dsh-standard':{name:'DeepSeek Harness 标准模式'}}}},
 candidates:[{plugins:[],check:{status:'passed'}}],operations:[{kind:'prepare_h0',state:'running',startedAt:1}]});

test('H0 does not unlock start during reference builds or before the operation completes',()=>{
 const c=fixture();
 assert.equal(campaignPreparation(c).ready,false);assert.match(campaignPreparation(c).label,/Codex.*DeepSeek/);
 c.config.referenceBindings.harnesses.codex.image='sha256:codex';
 assert.doesNotMatch(campaignPreparation(c).label,/Codex/);assert.match(campaignPreparation(c).label,/DeepSeek/);
 c.config.referenceBindings.harnesses['dsh-standard'].image='sha256:dsh';
 assert.equal(campaignPreparation(c).ready,false);
 c.operations[0].state='finished';assert.equal(campaignPreparation(c).ready,true);
});

test('failure and missing receipts block start; disabled plugins and legacy activities remain usable',()=>{
 const c=fixture();c.operations[0].state='failed';
 assert.equal(campaignPreparation(c).ready,false);assert.match(campaignPreparation(c).label,/失败/);
 c.operations.push({kind:'prepare_h0',state:'finished',startedAt:2});
 assert.equal(campaignPreparation(c).ready,false);assert.match(campaignPreparation(c).label,/尚未就绪/);
 c.references={policy:{harnessEnabled:false}};assert.equal(campaignPreparation(c).ready,true);
 delete c.references;delete c.config.referencePolicy;c.operations=[];
 assert.equal(campaignPreparation(c).ready,true);
 c.candidates=[];assert.equal(campaignPreparation(c).ready,false);
});

test('actual start button stays disabled until preparation succeeds and respects connectivity',async()=>{
 const result=await build({entryPoints:['packages/meta-workbench-studio/client/components/campaign.tsx'],bundle:true,write:false,format:'cjs',platform:'browser',external:['react','react/jsx-runtime'],jsx:'automatic'});
 const jsx=(type,props)=>({type,props});
 const sandbox={module:{exports:{}},exports:null,require:()=>({jsx,jsxs:jsx,Fragment:Symbol('Fragment')})};sandbox.exports=sandbox.module.exports;
 vm.runInNewContext(result.outputFiles[0].text,sandbox);
 const c=fixture(),commands=[],w={c,busy:'',connected:true,command:a=>commands.push(a)};
 const button=()=>sandbox.module.exports.CampaignActions({w}).props.children[0];
 assert.equal(button().props.disabled,true);assert.match(button().props.children,/Codex/);
 c.operations[0].state='failed';assert.equal(button().props.disabled,true);assert.match(button().props.children,/失败/);
 c.operations[0].state='finished';assert.equal(button().props.disabled,true);
 for(const h of Object.values(c.config.referenceBindings.harnesses))h.image='sha256:ready';
 assert.equal(button().props.disabled,false);assert.equal(button().props.children,'启动进化');
 w.connected=false;assert.equal(button().props.disabled,true);
 w.connected=true;w.busy='start';assert.equal(button().props.disabled,true);
 w.busy='';button().props.onClick();assert.deepEqual(commands,['start']);
});
