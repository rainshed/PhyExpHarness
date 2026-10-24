import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {build} from 'esbuild';
import {MetaHost} from '../../src/control/meta_host.mjs';

async function component(){
 const result=await build({entryPoints:['packages/meta-workbench-studio/client/components/failure.tsx'],bundle:true,write:false,format:'cjs',platform:'browser',external:['react','react/jsx-runtime'],jsx:'automatic'});
 const jsx=(type,props)=>({type,props});
 const sandbox={module:{exports:{}},exports:null,require:()=>({jsx,jsxs:jsx,Fragment:Symbol('Fragment')})};sandbox.exports=sandbox.module.exports;
 vm.runInNewContext(result.outputFiles[0].text,sandbox);
 function render(node){if(node==null||typeof node==='boolean')return '';if(Array.isArray(node))return node.map(render).join('');if(typeof node!=='object')return String(node);if(typeof node.type==='function')return render(node.type(node.props));return render(node.props?.children);}
 return trial=>render(sandbox.module.exports.FailureDetail({trial}));
}
test('trial detail separates official zero, absent score, recovered requests and container warnings',async()=>{
 const show=await component();
 const base={taskAssessment:{rule:'task-completion-v4',score:0,reason:'official_result'}};
 const zero=show({...base,score:0,scoringStatus:'completed',diagnosis:{category:'task_result',categoryLabel:'正式评分未通过',causeNote:'见评分报告',impactLabel:'已有官方评分'}});
 assert.match(zero,/正式评分未通过/);assert.match(zero,/官方评分：0/);assert.doesNotMatch(zero,/官方评分：未评分/);
 const missing=show({...base,score:null,scoringStatus:'not_run',diagnosis:{category:'platform',categoryLabel:'平台执行或控制'},failure:{code:'container_transport_error',message:'执行结果未知',stage:'execution'}});
 assert.match(missing,/平台执行或控制/);assert.match(missing,/官方评分：未评分/);assert.match(missing,/任务完成分：0/);
 const recovered=show({...base,score:1,scoringStatus:'completed',taskAssessment:{...base.taskAssessment,score:1},
  requestRecovery:{failedRequests:1,recoveredRequests:1,failures:[{code:'model_service_overloaded',categoryLabel:'模型服务或连接',message:'模型服务暂时不可用',requestId:'old',recoveredBy:'new'}]},
  containerTransport:{verificationBlocked:false,issues:[{callId:'command',executionState:'completed',blocksVerification:false,recoveredBy:'next'}]}});
 assert.match(recovered,/确认恢复 1 次/);assert.match(recovered,/已确认恢复/);assert.match(recovered,/异常未阻断评分/);assert.match(recovered,/官方评分：1/);
 assert.doesNotMatch(recovered,/查看失败原因|任务未能恢复/);
});
test('Meta host propagates database code and leaves write outcome unknown after lost response',async()=>{
 const host=new MetaHost({});
 host.dispatch=async function*(){throw Object.assign(Error('控制数据库暂时繁忙'),{controlFailure:{code:'control_database_busy',status:503,retryAfterMs:500}});};
 const recorded=[];const binding={outputs:{tool:record=>{recorded.push(record);return {path:'/outputs/fixture.log'};}}};
 for(const operation of ['campaign_status','report_save']){
  await assert.rejects(async()=>{for await(const unused of host.handle(binding,'meta',{action:'call',input:{operation}})){}},error=>{
   const receipt=JSON.parse(error.message);
   assert.equal(receipt.code,'control_database_busy');assert.equal(receipt.retryAfterMs,500);
   assert.equal(receipt.status,operation==='report_save'?'outcome_unknown':'failed');return true;
  });
 }
 assert.equal(recorded[0].controlFailure.code,'control_database_busy');
});
