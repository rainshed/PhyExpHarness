import {test} from 'node:test';
import assert from 'node:assert/strict';
import {comparison,defaultVersions,comparisonTasks,taskMean,outcomeNote,versionCost,reportGroups,reportCampaign,trialsFor} from '../../packages/meta-workbench-studio/client/readability.mjs';
const stats=(passed,eligible)=>({attempts:eligible,passed,eligible,successRate:eligible?passed/eligible:null});
const row=(id,task='a',limit=100)=>({id:id+task, candidateId:id,task,taskTimeLimitSeconds:limit,comparisonContext:{taskSourcesDigest:'source',runnerImageId:'image',runnerExecutionManifest:'proof',verifierImageId:'verifier',taskImageIds:[]}});
const campaign=()=>({id:'activity',config:{tasks:['a','b']},retainedCandidateId:'h1',trials:[row('h0'),row('h1')],tables:{rounds:[],versions:[{id:'h0',taskEvaluation:{byTask:{a:stats(1,3),b:stats(0,3)}}},{id:'h1',taskEvaluation:{byTask:{a:stats(1,1),b:{attempts:1,eligible:0,successRate:null,external_failure:1}}}}]}});
function withTrials(c){c.tables.rounds=c.trials.map(t=>({candidateId:t.candidateId,results:[t]}));return c;}
test('version task statistics preserve missing scores, full coverage, and common-task scope',()=>{
 const c=campaign(),v=c.tables.versions;
 assert.equal(taskMean(v[0],['a','b']),1/6);assert.equal(taskMean(v[1],['a','b']),null);
 assert.deepEqual(comparisonTasks(c,v,true),['a']);assert.equal(taskMean(v[1],['a']),1);
 assert.equal(outcomeNote(v[1].taskEvaluation.byTask.b),'未计分故障 1');assert.equal(outcomeNote(undefined),'未测');
 assert.equal(taskMean(v[0],[]),null);
});
test('known budget differences stay visible with a warning; missing provenance remains unknown',()=>{
 const c=withTrials(campaign());assert.equal(comparison(c,'h1','h0').state,'same');assert.deepEqual(defaultVersions(c),['h0','h1']);
 c.trials[1].taskTimeLimitSeconds=200;assert.equal(comparison(c,'h1','h0').state,'different');assert.deepEqual(defaultVersions(c),['h0','h1']);
 c.trials[1].taskTimeLimitSeconds=100;delete c.trials[1].comparisonContext; c.tables.rounds[1].results=[c.trials[1]];
 assert.equal(comparison(c,'h1','h0').state,'unknown');assert.deepEqual(defaultVersions(c),['h0','h1']);
});
test('image proofs must exist on all attempts, mixed budgets inside a version remain flagged',()=>{
 const c=withTrials(campaign());c.trials[1].comparisonContext.runnerImageId='other';assert.equal(comparison(c,'h1','h0').state,'same');
 delete c.trials[1].comparisonContext.runnerExecutionManifest;assert.equal(comparison(c,'h1','h0').state,'different');
 const more={...row('h1','a',50),id:'extra'};c.trials.push(more);withTrials(c);assert.equal(comparison(c,'h1','h1').state,'different');
});
test('duration summary omits accounting and preserves incomplete timing',()=>{
 assert.equal(versionCost([{}]).tokens,undefined);assert.equal(versionCost([{}]).seconds,null);
 const cost=versionCost([{accountedUsage:{confirmedTokens:100,unknownRequests:1},startedAt:0,finishedAt:10},{usage:{tokens:900},startedAt:5}]);
 assert.deepEqual(cost,{attempts:2,seconds:10,timed:1});
});
test('report ordering selects newest revision independently of backend list order',()=>{
 const r=[{id:'old',batchId:'b',kind:'round',analysisRevision:1,createdAt:5},{id:'latest',batchId:'b',kind:'round',analysisRevision:3,createdAt:7},{id:'middle',batchId:'b',kind:'round',analysisRevision:2,createdAt:6},{id:'summary',kind:'status_summary',createdAt:8}];
 assert.deepEqual(reportGroups(r,[{id:'b',round:1}]).map(x=>x.map(v=>v.id)),[['summary'],['latest','middle','old']]);
});
test('report comparison stays inside its frozen tables without computing usage',()=>{
 const r={facts:{campaign:{id:'activity',config:{tasks:['a']}},trials:[{...row('h1'),accountedUsage:{confirmedTokens:12}}]},tables:{rounds:[{candidateId:'h0',results:[row('h0')]},{candidateId:'h1',results:[row('h1')]}],versions:[]}};
 const c=reportCampaign(r);assert.equal(trialsFor(c).length,2);assert.equal(versionCost(trialsFor(c,'h0')).tokens,undefined);assert.equal(versionCost(trialsFor(c,'h1')).tokens,undefined);assert.equal(c.reports,undefined);
});

test('archived receipts and raw totals do not create new usage statistics',()=>{
 const cost=versionCost([{summary:{accounting:{confirmedTokens:20,unknownReservedTokens:30}}},{usage:{totalTokens:100}}]);
 assert.deepEqual(cost,{attempts:2,seconds:null,timed:0});
});

test('evidence pagination follows Unicode characters rather than UTF-16 units or bytes',async()=>{
 const {evidenceEnd}=await import('@phyexp/meta-workbench-client/evidence-text');
 assert.equal(evidenceEnd({offset:16000,text:'证据🧪α'}),16004);
 assert.equal(evidenceEnd({offset:4,text:''}),4);
});

test('overview defaults include latest candidate and filtered trial identities remain stable',async()=>{
 const {trialBucket,trialLabel,trialReport}=await import('../../packages/meta-workbench-studio/client/readability.mjs');
 const c=withTrials(campaign());c.tables.versions.push({id:'h2'});
 assert.deepEqual(defaultVersions(c),['h0','h1','h2']);
 c.tables.rounds=[{id:'b',round:4,candidateId:'h1',results:[{id:'first'},{id:'second'}]}];
 c.reports=[{id:'old',batchId:'b',analysisRevision:1},{id:'new',batchId:'b',analysisRevision:2}];
 assert.equal(trialLabel(c,{id:'second'}),'第 4 轮 · 实验 2');
 assert.equal(trialReport(c,{id:'second'}),'new');
 assert.deepEqual(['queued','running','failed','unknown'].map(state=>trialBucket({state})),['queued','active','ended','unknown']);
});

test('reading vocabulary translates known technical terms without inventing or truncating a conclusion',async()=>{
 const {readableText}=await import('../../packages/meta-workbench-studio/client/readability.mjs');
 assert.equal(readableText('官方null保留；v4完成分为0。没有stabilityRule。'),'官方未提供评分保留；任务完成分为0。没有可核验的稳定完成标准。');
 assert.equal(readableText('按v4仍计失败；budget_admission_denied。'),'按当前完成规则仍计失败；预算准入被拒绝。');
 const text='失败仍然保留；nullable 是标识；H1 为 1/2，净收益未知。';
 assert.equal(readableText(text),text);assert.equal(readableText(null),null);
});

test('whole candidate variations are separate from fixed process experiment conditions',()=>{
 const c=campaign();c.config.tasks=['a'];
 for(const t of c.trials){t.comparisonContext={taskSourcesDigest:'s',taskImageIds:['main','qsim'],verifierImageId:'verifier',runContract:'harbor-process-v1',adapter:{digest:'adapter'},brokerImageId:'broker',resources:{cpus:2},solver:{model:'fixed'}};
  t.effectiveConditions={timePolicy:'benchmark-time-v1',benchmarkTime:{solverTimeSeconds:1800},actualTimeSeconds:t.candidateId==='h0'?200:900};}
 withTrials(c);assert.equal(comparison(c,'h1','h0').state,'same');
 c.trials[1].comparisonContext.solver={model:'other'};assert.equal(comparison(c,'h1','h0').state,'different');
 delete c.trials[1].comparisonContext.adapter;assert.notEqual(comparison(c,'h1','h0').state,'same');
});

test('late starts compare actual windows and retain unknown timing as unknown',()=>{
 const c=withTrials(campaign());c.config.tasks=['a'];
 for(const t of c.trials)t.effectiveConditions={timePolicy:'benchmark-time-v2',solverTimeSeconds:9000,
  benchmarkTime:{solverTimeSeconds:9000,requiredTimeSeconds:10000},availableTimeSeconds:12000,effectiveSolverTimeSeconds:9000};
 assert.equal(comparison(c,'h1','h0').state,'same');
 c.trials[1].effectiveConditions.availableTimeSeconds=1800;
 c.trials[1].effectiveConditions.effectiveSolverTimeSeconds=1740;
 assert.equal(comparison(c,'h1','h0').state,'different');
 assert.ok(comparison(c,'h1','h0').reasons.includes('实验时限或实际预算不同'));
 c.trials[1].effectiveConditions.availableTimeSeconds=12000;
 delete c.trials[1].effectiveConditions.effectiveSolverTimeSeconds;
 assert.equal(comparison(c,'h1','h0').state,'unknown');
});
