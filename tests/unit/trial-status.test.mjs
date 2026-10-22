import test from 'node:test';
import assert from 'node:assert/strict';
import {trialStage,waitingReason,trialTiming,pendingSummary,outcomeNote,coverageLabel,contextTrials,reportContext,activityProgress} from '../../packages/meta-workbench/client/trial-status.mjs';
const queued={id:'q',state:'reserved',batchId:'b',scoringStatus:'pending',completionLabel:'任务结果待定；官方运行中，等待评分'};
const running={id:'r',state:'running',batchId:'b',startedAt:100,scoringStatus:'pending'};
const campaign={state:'running',config:{concurrency:5},counts:{activeTrials:5},batches:[{id:'b',acceptedAt:50}]};

test('queued, launching and running override legacy pending completion labels',()=>{
 assert.equal(trialStage(queued).label,'排队');
 assert.equal(trialStage({...queued,state:'launching'}).label,'启动中');
 assert.equal(trialStage({...running,completionLabel:queued.completionLabel}).label,'运行中 · 阶段未细分');
});
test('grading needs an explicit receipt, never inferred from pending, elapsed time or solver deadline',()=>{
 assert.equal(trialStage({...running,effectiveConditions:{solverDeadline:1}}).key,'running');
 assert.equal(trialStage({...running,phase:'verifier'}).label,'评分中');
 assert.equal(trialStage({...running,scoringStatus:'running'}).key,'scoring');
 assert.equal(trialStage({...running,phase:'execution'}).label,'运行中');
 assert.equal(trialStage({...running,phase:'collection'}).key,'collecting');
 assert.equal(trialStage({...running,state:'failed',phase:'verifier',completionLabel:'模型故障，按规则计零'}).label,'模型故障，按规则计零');
});
test('queue explains capacity, pause and unstarted campaign without promising a start time',()=>{
 assert.equal(waitingReason(queued,campaign),'并发名额已满（5/5），等待在途实验结束');
 assert.match(waitingReason(queued,{...campaign,state:'paused'}),/已暂停/);
 assert.match(waitingReason(queued,{...campaign,state:'draft'}),/尚未启动/);
 assert.match(waitingReason(queued,{...campaign,state:'closing'}),/不再启动/);
 assert.equal(waitingReason(running,campaign),null);
});
test('queue distinguishes missing plan, resource reservations and per-trial condition confirmation',()=>{
 assert.match(waitingReason(queued,{config:{resourcePolicy:'meta-resource-planning-v1'}}),/提交运行计划/);
 assert.match(waitingReason(queued,{resourcePlanning:{schedulingWait:{reason:'closeout_time'}}}),/收尾预留/);
 assert.match(waitingReason(queued,{resourcePlanning:{schedulingWait:{reason:'token_capacity'}}}),/token 额度/);
 assert.match(waitingReason({...queued,conditionsRequired:{requestedSeconds:100,availableSeconds:20}},campaign),/确认缩短/);
 assert.match(waitingReason(queued,{historical:true}),/快照未记录/);
 assert.match(waitingReason(queued,{}),/等待后台调度/);
});
test('elapsed time grows for live trials, stops on completion, and queue starts at batch acceptance',()=>{
 assert.equal(trialTiming(running,campaign,180).seconds,80);
 assert.equal(trialTiming(queued,campaign,180).seconds,130);
 assert.equal(trialTiming({...running,state:'completed',finishedAt:160},campaign,999).seconds,60);
 assert.equal(trialTiming({...running,state:'completed'},campaign,999).seconds,null);
 assert.equal(trialTiming({...running,startedAt:0},campaign,10).seconds,10);
 assert.equal(trialTiming(running,campaign,90).seconds,0);
});
test('historical running and queued durations are frozen; missing facts never use current clock',()=>{
 const historical={...campaign,historical:true,snapshotAt:160};
 assert.equal(trialTiming(running,historical,999).seconds,60);
 assert.equal(trialTiming(queued,historical,999).seconds,110);
 assert.equal(trialTiming(running,{historical:true},999).seconds,null);
 assert.equal(trialTiming(queued,{...historical,batches:[]},999).seconds,null);
});
test('pending breakdown retains unknown stages and deduplicates without inventing additional trials',()=>{
 const scoring={...running,id:'s',phase:'verifier'};
 assert.equal(pendingSummary(3,[queued,running,scoring]),'排队 1 · 运行中（阶段未细分） 1 · 评分中 1');
 assert.equal(pendingSummary(4,[queued,queued,running],true),'当时：排队 1 · 运行中（阶段未细分） 1 · 阶段未记录 2');
 assert.equal(pendingSummary(1,[queued,running]),'尚无结果 1（阶段未记录）');
 assert.equal(pendingSummary(0,[running]),'');
});
test('coverage is independent of execution completion and preserves official zero',()=>{
 assert.equal(coverageLabel({taskCount:5,coveredTasks:1,macroSuccessRate:null}),'覆盖不足，暂不计算');
 assert.equal(coverageLabel({taskCount:5,coveredTasks:5,macroSuccessRate:0}),'0.0%');
 assert.equal(outcomeNote({attempts:2,eligible:2,pending:0}), '');
 assert.equal(outcomeNote({attempts:1,external_failure:1}), '未计分故障 1');
 assert.equal(outcomeNote({attempts:1,pending:1},[queued]), '排队 1');
 assert.equal(outcomeNote({attempts:0}), '未测');
});
test('v4 keeps official absence in details while showing terminal failure and excluding unstarted attempts',()=>{
 const c={config:{taskEvaluationRule:'task-completion-v4'}};
 const failed={state:'failed',score:null,scoringStatus:'not_run',resultLabel:'未评分',completionLabel:'失败 · 评分器异常'};
 assert.equal(trialStage(failed).label,'失败 · 评分器异常');
 assert.equal(coverageLabel({taskCount:1,coveredTasks:1,macroSuccessRate:0}),'0.0%');
 assert.equal(outcomeNote({attempts:3,eligible:1,not_started:1,unresolved:1},[],c),'未执行 1 · 结束状态待核实 1');
 assert.equal(trialStage({...failed,state:'running'}).key,'running');
});
test('report revisions use the frozen activity clock, not a newer revision date',()=>{
 const c=reportContext({createdAt:9000,presentationSourceReportId:'old',facts:{campaign:{state:'running',startedAt:100,elapsedSeconds:60},trials:[running]}});
 assert.equal(c.snapshotAt,160);assert.equal(c.historical,true);
 assert.equal(trialTiming(c.trials[0],c,10000).seconds,60);
 const unknown=reportContext({createdAt:9000,presentationSourceReportId:'old',facts:{campaign:{}}});
 assert.equal(unknown.snapshotAt,null);
 assert.equal(reportContext({createdAt:200,facts:{campaign:{}}}).snapshotAt,200);
});
test('tables are enriched only from their supplied context, including older snapshot rows',()=>{
 const frozen={facts:{campaign:{state:'running',startedAt:100,elapsedSeconds:60},trials:[running]},tables:{rounds:[{id:'b',candidateId:'h0',results:[running,queued]}]}};
 const c=reportContext(frozen),before=JSON.stringify(frozen);
 assert.deepEqual(contextTrials(c).map(t=>[t.id,t.candidateId,t.batchId]),[['r','h0','b'],['q','h0','b']]);
 assert.match(activityProgress(c),/当时/);
 assert.equal(JSON.stringify(frozen),before);
 assert.equal(contextTrials({...c,trials:[]}).length,2);
});
