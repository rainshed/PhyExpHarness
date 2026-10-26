import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {build} from 'esbuild';
import {campaignStatus} from '../../packages/meta-workbench-studio/client/components/campaign-status.mjs';
import {reportTitle,reportCampaign} from '../../packages/meta-workbench-studio/client/readability.mjs';

test('closeout view preserves Meta text and distinguishes missing summaries and certification',async()=>{
 const result=await build({entryPoints:['packages/meta-workbench-studio/client/components/closeout.tsx'],bundle:true,write:false,format:'cjs',platform:'browser',external:['react','react/jsx-runtime'],jsx:'automatic'});
 const jsx=(type,props)=>({type,props});const sandbox={module:{exports:{}},exports:null,require:()=>({jsx,jsxs:jsx})};sandbox.exports=sandbox.module.exports;
 vm.runInNewContext(result.outputFiles[0].text,sandbox);
 const {Closeout}=sandbox.module.exports;
 const render=node=>node==null||typeof node==='boolean'?'':Array.isArray(node)?node.map(render).join(''):typeof node!=='object'?String(node):render(node.props?.children);
 const c={state:'finished',config:{stopPolicy:'meta-closeout-v1'},finishAssessment:{reason:'比较工作完成',summary:'两种方案都失败。\n尚不能证明改善。🧪'}};
 const text=render(Closeout({campaign:c}));assert.ok(text.includes(c.finishAssessment.reason));assert.ok(text.includes(c.finishAssessment.summary));
 assert.match(text,/活动结束不表示平台认证目标已经达成/);
 delete c.finishAssessment;assert.match(render(Closeout({campaign:c})),/尚未收到 Meta 提交/);
 c.state='running';assert.equal(Closeout({campaign:c}),null);
 assert.equal(Closeout({campaign:{state:'finished',config:{stopPolicy:'goal-or-budget-v1'}}}),null);
});

test('committed closeout needs no model recovery and report snapshots retain the decision',()=>{
 const c={state:'closing',config:{stopPolicy:'meta-closeout-v1'},finishAssessment:{reason:'完成比较',summary:'总结'},metaSessions:[{state:'needs_attention'}]};
 assert.equal(campaignStatus(c).label,'收尾中');assert.equal(campaignStatus(c).attention,false);
 const report={closeoutSubmitted:true,kind:'status_summary',status:'analysis_incomplete',facts:{campaign:c,trials:[]},tables:{versions:[],rounds:[]}};
 assert.equal(reportTitle(report),'收尾记录与最终事实');assert.deepEqual(reportCampaign(report).finishAssessment,c.finishAssessment);
 assert.equal(reportTitle({kind:'status_summary',status:'analysis_incomplete'}),'阶段摘要 · 分析未完成');
});
