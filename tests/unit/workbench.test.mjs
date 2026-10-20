import {test} from 'node:test';
import assert from 'node:assert/strict';
import {configError,numericConfig} from '../../packages/meta-workbench/client/form.mjs';
import {loadGoalDraft,defaultObjective} from '../../packages/meta-workbench/client/goal.mjs';
import {createAttempt} from '../../packages/meta-workbench/client/create-attempt.mjs';

test('an unchanged create retry survives reload without duplicating a campaign',()=>{
 let keys=0;const key=()=>String(++keys);
 const config={name:'Draft',concurrency:3,maxTrials:null};
 const first=createAttempt(config,null,key);
 const restored=JSON.parse(JSON.stringify(first));
 assert.deepEqual(createAttempt({...config},restored,key),first);
 assert.equal(keys,1);
 assert.notEqual(createAttempt({...config,concurrency:4},restored,key).key,first.key);
 assert.notEqual(createAttempt(config,null,key).key,first.key);
});

test('goal defaults upgrade only the previous literal default and preserve custom drafts and limits',()=>{
 const data=new Map();const storage={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)};
 const old='基于真实执行证据，开发并测试至少一个可复用的执行插件，说明其作用与局限，生成每轮及最终报告。改进方法由 Meta 自主决定。';
 const raw=JSON.stringify({objective:old,maxTrials:7});data.set('phyexp-draft',raw);
 assert.deepEqual(loadGoalDraft(storage,{}),{objective:defaultObjective,maxTrials:7});
 assert.equal(data.get('phyexp-draft-before-meta-goal-v1'),raw);
 for(const goal of ['自定义目标','']){data.set('phyexp-draft',JSON.stringify({objective:goal}));assert.equal(loadGoalDraft(storage,{}).objective,goal);}
});

test('saved drafts acquire the new-activity planning policy without replacing chosen limits',()=>{
 const draft={name:'Saved',reserveSeconds:0,softTokenLimit:null,concurrency:5};
 const restored=loadGoalDraft({getItem:()=>JSON.stringify(draft)},
  {resourcePolicy:'meta-resource-planning-v1',reserveSeconds:null,concurrency:1});
 assert.deepEqual(restored,{resourcePolicy:'meta-resource-planning-v1',...draft});
});

const valid={name:'Test',tasks:['one'],maxRounds:'4',maxTrials:'4',concurrency:'1',wallTimeSeconds:'14400',trialTimeSeconds:'2700',softTokenLimit:'8000000',reserveSeconds:'1800',reserveTokens:'800000',stopMode:'strict'};
test('creation identifies insufficient baseline slots without silently raising budget',()=>{
 const config={...valid,tasks:['one','two','three'],maxTrials:'2'};
 assert.match(configError(config),/3 个任务.*至少需要 3 次实验.*当前最多实验次数为 2/);
 assert.equal(config.maxTrials,'2');
});
test('typed limits preserve integers and reject blank, unsafe and inconsistent bounds',()=>{
 assert.equal(configError(valid),'');assert.equal(numericConfig(valid).maxTrials,4);
 for(const value of ['', '1.5','-1','9007199254740993'])assert.match(configError({...valid,maxTrials:value}),/整数/);
 assert.match(configError({...valid,reserveSeconds:'14400'}),/预留时间/);
 assert.match(configError({...valid,reserveTokens:'8000000'}),/预留 token/);
 assert.match(configError({...valid,concurrency:'5'}),/并发/);
 assert.match(configError({...valid,stopMode:'drain',drainGraceSeconds:'901'}),/900/);
});

test('optional caps preserve null while blank custom inputs remain invalid',()=>{
 const config={...valid,maxRounds:null,maxTrials:null,trialTimeSeconds:null,softTokenLimit:null,reserveSeconds:null,reserveTokens:null,concurrency:'3',wallTimeSeconds:'12600'};
 assert.equal(configError(config),'');
 assert.equal(numericConfig(config).maxRounds,null);
 assert.equal(numericConfig(config).softTokenLimit,null);
 assert.ok(configError({...config,maxRounds:''}));
 assert.ok(configError({...config,wallTimeSeconds:null}));
});


test('old backend catalog names preserve selectable GPT subscriptions during an upgrade',async()=>{
 const {readModelCatalog}=await import('../../packages/meta-workbench/client/model-catalog.mjs');
 const result=readModelCatalog({models:['gpt-6-sol','gpt-6-astra','gpt-6-luna'],provider:'openai-codex'});
 for(const id of ['gpt-6-sol','gpt-6-astra','gpt-6-luna']){
  const model=result.models.find(m=>m.provider==='openai-codex'&&m.model===id);
  assert.ok(model);assert.equal(model.defaultReasoningEffort,'medium');assert.ok(model.reasoningEfforts.includes('medium'));
 }
 assert.match(result.note,/重启后台/);
});

test('new catalog retains custom capabilities and rejects malformed rows before draft matching',async()=>{
 const {readModelCatalog}=await import('../../packages/meta-workbench/client/model-catalog.mjs');
 const model={provider:'custom',model:'fixture',name:'Custom',reasoningEfforts:[],defaultReasoningEffort:null};
 assert.deepEqual(readModelCatalog({models:[model]}),{models:[model],note:''});
 const thinking={...model,reasoningEfforts:['off','high'],defaultReasoningEffort:'high'};
 assert.deepEqual(readModelCatalog({models:[thinking]}).models,[thinking]);
 for(const payload of [{models:[]},{models:['unknown'],provider:'custom'},{models:['gpt-6-sol',model]},
                      {models:[{...model,reasoningEfforts:['high']}]},{models:[model,model]}])assert.throws(()=>readModelCatalog(payload),/后台/);
});

test('an explicitly versioned empty directory is usable after all providers are disabled',async()=>{
 const {readModelCatalog}=await import('../../packages/meta-workbench/client/model-catalog.mjs');
 assert.deepEqual(readModelCatalog({schemaVersion:2,models:[]}),{models:[],note:''});
});
