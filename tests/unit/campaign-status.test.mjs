import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {build} from 'esbuild';
import {campaignStatus,metaFailureReason} from '../../packages/meta-workbench-studio/client/components/campaign-status.mjs';

const blocked=()=>({id:'meta-old',state:'needs_attention',recovery:{reason:'recovery_exhausted',failure:{code:'model_transport_error',observed:{transport:{errorCode:'ETIMEDOUT'}}}}});
test('active lifecycle does not hide a stopped Meta, including during closeout',()=>{
 for(const state of ['running','closing']){
  const status=campaignStatus({state,metaSessions:[blocked()]});
  assert.equal(status.label,'需要处理');assert.equal(status.reason,'连接模型服务超时');assert.match(status.recoveryNote,/已用完/);
 }
 const list=campaignStatus({state:'running',metaStatus:{sessionId:'meta-old',state:'needs_attention',recoveryReason:'recovery_exhausted',failure:{code:'model_transport_error'},connectionTimedOut:true}});
 assert.equal(list.label,'需要处理');assert.equal(list.reason,'连接模型服务超时');
});
test('new healthy session clears historical failures and stale list health',()=>{
 const c={state:'running',metaStatus:{state:'needs_attention'},metaSessions:[blocked(),{id:'meta-new',state:'running'}]};
 assert.equal(campaignStatus(c).label,'运行中');assert.equal(campaignStatus(c).attention,false);
 c.metaSessions.at(-1).state='waiting';assert.equal(campaignStatus(c).attention,false);
});
test('paused and terminal lifecycles are not overwritten by old failures',()=>{
 for(const [state,label] of [['paused','已暂停'],['finished','已结束'],['failed','失败'],['draft','待启动']]){
  const status=campaignStatus({state,metaSessions:[blocked()]});assert.equal(status.label,label);assert.equal(status.attention,false);assert.equal(status.reason,'');
 }
});
test('recoverable and nonrecoverable failures have distinct actionable descriptions',()=>{
 const session={...blocked(),state:'recovering',recovery:{failure:{code:'model_service_overloaded'}}};
 const status=campaignStatus({state:'running',metaSessions:[session]});
 assert.equal(status.label,'正在恢复');assert.equal(status.attention,false);assert.equal(status.reason,'模型服务暂时过载');
 session.state='needs_attention';session.recovery={reason:'nonrecoverable',failure:{code:'accounting_auth_failed'}};
 assert.match(campaignStatus({state:'running',metaSessions:[session]}).recoveryNote,/不适合自动重试/);
 assert.equal(metaFailureReason(session),'后台请求凭证验证失败');
});
test('missing failure details stay unknown and raw errors are not used as the headline',()=>{
 assert.equal(campaignStatus({state:'running'}).label,'运行中');
 assert.match(metaFailureReason({state:'needs_attention',summary:{error:'SECRET raw stack'}}),/原因尚未确认/);
 assert.match(metaFailureReason({failure:{code:'new_failure',message:'SECRET raw provider error'}}),/原因尚未确认/);
 const c={state:'running',metaSessions:[{id:'current',state:'needs_attention',summary:{error:'SECRET'}}],metaStatus:{sessionId:'current',failure:{code:'stream_whitespace',message:'工具参数持续输出空白'}}};
 assert.equal(campaignStatus(c).reason,'工具参数持续输出空白');
 c.metaStatus.sessionId='previous';assert.match(campaignStatus(c).reason,/原因尚未确认/);
});
test('notice separates stopped research from active experiments and supplies a details action',async()=>{
 const result=await build({entryPoints:['packages/meta-workbench-studio/client/components/campaign.tsx'],bundle:true,write:false,format:'cjs',platform:'browser',external:['react','react/jsx-runtime'],jsx:'automatic'});
 const jsx=(type,props)=>({type,props});
 const sandbox={module:{exports:{}},exports:null,require:()=>({jsx,jsxs:jsx,Fragment:Symbol('Fragment')})};sandbox.exports=sandbox.module.exports;
 vm.runInNewContext(result.outputFiles[0].text,sandbox);
 const {CampaignNotices}=sandbox.module.exports;
 const render=node=>node==null||typeof node==='boolean'?'':Array.isArray(node)?node.map(render).join(''):typeof node!=='object'?String(node):render(node.props?.children);
 const c={state:'running',metaSessions:[blocked()],config:{},counts:{activeTrials:2,reservedTrials:1}};
 const notice=CampaignNotices({c,onDetails(){}}),text=render(notice);
 assert.match(text,/需要处理 · Meta 已停止推进/);assert.match(text,/连接模型服务超时/);
 assert.match(text,/已启动的 2 次实验仍由后台继续执行/);assert.match(text,/另有 1 次已受理实验/);
 assert.match(text,/暂停新工作.*恢复活动/);assert.match(text,/查看中断详情/);assert.match(text,/墙钟仍在计时/);
 assert.equal(notice.props.children[0].props.role,'alert');
 c.counts.activeTrials=0;assert.match(render(CampaignNotices({c})),/当前没有正在执行的实验/);
 c.metaSessions.push({state:'running'});assert.doesNotMatch(render(CampaignNotices({c})),/需要处理|连接模型服务超时/);
});
