import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {build} from 'esbuild';
import {campaignStatus,metaFailureReason} from '../../packages/meta-workbench-studio/client/components/campaign-status.mjs';

const blocked=()=>({id:'meta-old',state:'needs_attention',recovery:{reason:'recovery_exhausted',failure:{code:'model_transport_error',observed:{transport:{errorCode:'ETIMEDOUT'}}}}});
test('storage failures remain the headline when model cancellation is secondary',()=>{
 const c={state:'running',metaSessions:[{state:'needs_attention',summary:{failure:{code:'storage_write_error',secondaryCodes:['request_cancelled']}}}]};
 assert.equal(campaignStatus(c).reason,'日志写入失败，请检查存储状态与文件权限');
});
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
 session.state='recovering';session.recovery.userResumedAt=123;
 assert.equal(campaignStatus({state:'running',metaSessions:[session]}).manualRecovery,true);
 assert.equal(campaignStatus({state:'running',metaStatus:{state:'recovering',recoveryRequested:true}}).manualRecovery,true);
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
 let resumed=0;const onResume=()=>resumed++;
 const notice=CampaignNotices({c,onDetails(){},onResume}),text=render(notice);
 assert.match(text,/需要处理 · Meta 已停止推进/);assert.match(text,/连接模型服务超时/);
 assert.match(text,/已启动的 2 次实验仍由后台继续执行/);assert.match(text,/另有 1 次已受理实验/);
 assert.match(text,/点击“恢复活动”即可继续/);assert.doesNotMatch(text,/暂停新工作/);assert.match(text,/查看中断详情/);assert.match(text,/墙钟仍在计时/);
 assert.equal(notice.props.children[0].props.role,'alert');
 const elements=node=>Array.isArray(node)?node.flatMap(elements):node&&typeof node==='object'?[node,...elements(node.props?.children)]:[];
 const resumeButton=props=>elements(CampaignNotices({c,onResume,...props})).find(node=>node.type==='button');
 assert.equal(resumeButton({}).props.disabled,false);resumeButton({}).props.onClick();assert.equal(resumed,1);
 assert.equal(resumeButton({busy:'resume'}).props.disabled,true);assert.equal(render(resumeButton({busy:'resume'})),'正在提交恢复…');
 assert.equal(resumeButton({connected:false}).props.disabled,true);
 c.remainingSeconds=0;assert.equal(resumeButton({}).props.disabled,true);assert.match(render(CampaignNotices({c,onResume})),/已到截止时间/);
 delete c.remainingSeconds;
 const pending={...c,metaSessions:[{...blocked(),state:'recovering',recovery:{userResumedAt:123}}]};
 const pendingText=render(CampaignNotices({c:pending,onResume}));assert.match(pendingText,/恢复请求已受理/);assert.doesNotMatch(pendingText,/自动恢复|需要处理/);
 c.counts.activeTrials=0;assert.match(render(CampaignNotices({c})),/当前没有正在执行的实验/);
 c.metaSessions.push({state:'running'});assert.doesNotMatch(render(CampaignNotices({c})),/需要处理|连接模型服务超时/);
});
