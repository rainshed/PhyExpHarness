import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import catalog from '../../src/execution/host/model-catalog.json' with {type:'json'};

const run=promisify(execFile),source=path.resolve('.');
const base=JSON.parse(fs.readFileSync('recipes/h0-sol.json'));
const cases=[];
for(const [provider,route] of Object.entries(catalog.providers))for(const model of route.models)
 for(const reasoningEffort of model.reasoningEfforts?Object.keys(model.reasoningEfforts):[undefined])
  cases.push({provider,model:model.id,reasoningEffort,providerConfig:{...route,models:[model]}});
// Custom effort mappings and non-reasoning models must follow the frozen route too.
for(const reasoningEffort of [undefined,'max'])cases.push({provider:'offline-assembly',model:'fixture',reasoningEffort,
 providerConfig:{adapter:'pi-ai',api:'openai-completions',baseURL:'https://offline.invalid/v1',
  auth:{type:'api-key',env:'PHYEXP_ASSEMBLY_MISSING_KEY'},models:[{id:'fixture',contextWindow:32000,
   reasoningEfforts:reasoningEffort?{max:'high'}:false,...(reasoningEffort?{defaultReasoningEffort:'max'}:{})}]}});

for(const selected of cases)test(`frozen assembly accepts ${selected.provider}/${selected.model}/${selected.reasoningEffort??'no reasoning'}`,
 {timeout:45000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp assembly '));
 try{
  const recipe={...base,...selected};
  fs.writeFileSync(path.join(dir,'recipe.json'),JSON.stringify(recipe));
  const frozen=await run(process.env.PYTHON||'python3',['-c',
   "import json,sys;from pathlib import Path;from src.execution.bundle.freeze import freeze;print(json.dumps(freeze(Path.cwd(),Path(sys.argv[1])/'bundles',json.loads((Path(sys.argv[1])/'recipe.json').read_text()))))",dir],{cwd:source});
  const bundle=JSON.parse(frozen.stdout),logs=path.join(dir,'check');
  // Only host test dependencies are shared; the native Runner uses the Bundle's locked Docker image.
  fs.symlinkSync(path.join(source,'node_modules'),path.join(bundle.path,'node_modules'),'dir');
  fs.mkdirSync(logs);
  await run(process.execPath,[path.join(bundle.path,'src/execution/bundle/check.mjs'),bundle.path,logs],
   {cwd:dir,timeout:35000,env:{...process.env,PHYEXP_CODEX_AUTH_FILE:path.join(dir,'missing-auth.json'),
    DEEPSEEK_API_KEY:'',PHYEXP_ASSEMBLY_MISSING_KEY:''}});
  const assembly=JSON.parse(fs.readFileSync(path.join(logs,'assembly.json')));
  assert.equal(assembly.status,'passed');assert.equal(assembly.model,'controlled-fake-provider');assert.equal(assembly.bundleId,bundle.id);
  const config=JSON.parse(fs.readFileSync(path.join(logs,'runner-config/runner.json')));
  assert.deepEqual(new Set(config.modelInfo.reasoning?.efforts.map(e=>e.id)??[]),new Set(selected.providerConfig.models[0].reasoningEfforts?Object.keys(selected.providerConfig.models[0].reasoningEfforts):[]));
  if(selected.providerConfig.models[0].contextWindow)assert.equal(config.modelInfo.context.contextWindow,selected.providerConfig.models[0].contextWindow);
  const audit=fs.readFileSync(path.join(logs,'check-gateway.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
  const requests=audit.filter(e=>e.type==='request');assert.equal(requests.length,1);
  for(const key of ['provider','model','reasoningEffort','maxTokens'])assert.equal(requests[0].request[key],recipe[key]);
  assert.equal(audit.filter(e=>e.type==='rejected').length,0);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
