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
test('known budget differences excluded by default; missing provenance remains unknown',()=>{
 const c=withTrials(campaign());assert.equal(comparison(c,'h1','h0').state,'same');assert.deepEqual(defaultVersions(c),['h0','h1']);
 c.trials[1].taskTimeLimitSeconds=200;assert.equal(comparison(c,'h1','h0').state,'different');assert.deepEqual(defaultVersions(c),['h0']);
 c.trials[1].taskTimeLimitSeconds=100;delete c.trials[1].comparisonContext; c.tables.rounds[1].results=[c.trials[1]];
 assert.equal(comparison(c,'h1','h0').state,'unknown');assert.deepEqual(defaultVersions(c),['h0','h1']);
});
test('image proofs must exist on all attempts, mixed budgets inside a version remain flagged',()=>{
 const c=withTrials(campaign());c.trials[1].comparisonContext.runnerImageId='other';assert.equal(comparison(c,'h1','h0').state,'same');
 delete c.trials[1].comparisonContext.runnerExecutionManifest;assert.equal(comparison(c,'h1','h0').state,'different');
 const more={...row('h1','a',50),id:'extra'};c.trials.push(more);withTrials(c);assert.equal(comparison(c,'h1','h1').state,'different');
});
test('cost is a labeled ledger subtotal, missing use and incomplete timing never become zero',()=>{
 assert.equal(versionCost([{}]).tokens,null);assert.equal(versionCost([{}]).seconds,null);
 const cost=versionCost([{accountedUsage:{confirmedTokens:100,unknownRequests:1},startedAt:0,finishedAt:10},{usage:{tokens:900},startedAt:5}]);
 assert.deepEqual(cost,{tokens:100,recorded:1,attempts:2,unknown:1,unknownReserved:0,seconds:10,timed:1});
});
test('report ordering selects newest revision independently of backend list order',()=>{
 const r=[{id:'old',batchId:'b',kind:'round',analysisRevision:1,createdAt:5},{id:'latest',batchId:'b',kind:'round',analysisRevision:3,createdAt:7},{id:'middle',batchId:'b',kind:'round',analysisRevision:2,createdAt:6},{id:'summary',kind:'status_summary',createdAt:8}];
 assert.deepEqual(reportGroups(r,[{id:'b',round:1}]).map(x=>x.map(v=>v.id)),[['summary'],['latest','middle','old']]);
});
test('report comparison stays inside its frozen tables and does not invent older ledger totals',()=>{
 const r={facts:{campaign:{id:'activity',config:{tasks:['a']}},trials:[{...row('h1'),accountedUsage:{confirmedTokens:12}}]},tables:{rounds:[{candidateId:'h0',results:[row('h0')]},{candidateId:'h1',results:[row('h1')]}],versions:[]}};
 const c=reportCampaign(r);assert.equal(trialsFor(c).length,2);assert.equal(versionCost(trialsFor(c,'h0')).tokens,null);assert.equal(versionCost(trialsFor(c,'h1')).tokens,12);assert.equal(c.reports,undefined);
});

test('archived accounting receipts support live cost without treating raw model totals as confirmed',()=>{
 const cost=versionCost([{summary:{accounting:{confirmedTokens:20,unknownReservedTokens:30}}},{usage:{totalTokens:100}}]);
 assert.equal(cost.tokens,20);assert.equal(cost.recorded,1);assert.equal(cost.unknownReserved,30);
});

test('evidence pagination follows Unicode characters rather than UTF-16 units or bytes',async()=>{
 const {evidenceEnd}=await import('@phyexp/meta-workbench-client/evidence-text');
 assert.equal(evidenceEnd({offset:16000,text:'证据🧪α'}),16004);
 assert.equal(evidenceEnd({offset:4,text:''}),4);
});
