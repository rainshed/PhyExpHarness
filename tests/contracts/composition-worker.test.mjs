import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';

const run=promisify(execFile),source=path.resolve('.');
test('stored composition worker recovers an HTTP overload and loads immutable plugin configuration',{timeout:60000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp composition worker '));
 let requests=0,providerFailure;
 const server=http.createServer(async(req,res)=>{
  try{
   let input='';for await(const chunk of req)input+=chunk;
   const body=JSON.parse(input);requests++;
   assert.equal(req.headers.authorization,'Bearer fixture-composition-key');
   assert.equal(body.model,'fixture-model');
   assert.deepEqual(new Set(body.tools.map(t=>t.function.name)),new Set(['bash','example_echo']));
   if(requests===1){res.writeHead(503,{'content-type':'application/json'});res.end(JSON.stringify({error:{message:'Our servers are currently overloaded.',type:'server_error'}}));return;}
   let delta,reason;
   if(requests===2){
    delta={role:'assistant',tool_calls:[{index:0,id:'echo-call',type:'function',function:{name:'example_echo',arguments:'{"text":"payload"}'}}]};
    reason='tool_calls';
   }else{
    assert.equal(requests,3);
    assert.ok(body.messages.some(m=>m.role==='tool'&&m.content.includes('frozen:payload')));
    delta={role:'assistant',content:'fixture completed'};reason='stop';
   }
   const events=[{id:'fixture',object:'chat.completion.chunk',model:body.model,choices:[{index:0,delta,finish_reason:null}]},
    {id:'fixture',object:'chat.completion.chunk',model:body.model,choices:[{index:0,delta:{},finish_reason:reason}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12}}];
   res.writeHead(200,{'content-type':'text/event-stream'});
   res.end(events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join(''));
  }catch(error){providerFailure=error;res.writeHead(500);res.end('Fixture assertion failed');}
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{
  const plugin=path.join(dir,'draft');fs.mkdirSync(plugin);
  fs.copyFileSync(path.join(source,'knowledge/plugin-sdk/examples/echo.mjs'),path.join(plugin,'index.mjs'));
  fs.writeFileSync(path.join(plugin,'plugin.json'),JSON.stringify({schemaVersion:1,name:'technical-echo',version:'1.0.0',entry:'index.mjs',
   purpose:'Technical fixture',configSchema:{type:'object'},dependencies:[],observes:[],intervenes:[],capabilities:['tools','public-context','tool-results'],
   fallbackBehavior:'Propagate errors',assets:[],tools:['example_echo']}));
  const recipe={...JSON.parse(fs.readFileSync('recipes/h0-sol.json')),provider:'offline-composition',model:'fixture-model',maxTokens:1024,
   providerConfig:{adapter:'pi-ai',api:'openai-completions',baseURL:`http://127.0.0.1:${server.address().port}/v1`,
    auth:{type:'api-key',env:'PHYEXP_COMPOSITION_FIXTURE_KEY'},models:[{id:'fixture-model',reasoningEfforts:false,maxTokens:1024,contextWindow:16000}]}};
  delete recipe.reasoningEffort;
  fs.writeFileSync(path.join(dir,'recipe.json'),JSON.stringify(recipe));
  const frozen=await run(process.env.PYTHON||'python3',['-c',
   "import json,sys;from pathlib import Path;from src.execution.bundle.freeze import freeze;from src.control.execution_cache import prepare_runtime;p=Path(sys.argv[1]);b=freeze(Path.cwd(),p/'objects',json.loads((p/'recipe.json').read_text()),[{'path':p/'draft','config':{'prefix':'frozen:'}}]);b['runtime']=str(prepare_runtime(b['path'],p/'cache',install=False));print(json.dumps(b))",dir],{cwd:source});
  const bundle=JSON.parse(frozen.stdout);
  // Unit/contract host dependency shortcut; ZIP relocation separately installs exact locks.
  fs.symlinkSync(path.join(source,'node_modules'),path.join(bundle.runtime,'node_modules'),'dir');
  fs.writeFileSync(path.join(plugin,'index.mjs'),'throw Error("draft must never run");');
  const logs=path.join(dir,'logs');fs.mkdirSync(logs);
  for(const [name,value] of Object.entries({'mcp-connections.json':[],'environment.json':{mcpServers:[]}}))
   fs.writeFileSync(path.join(logs,name),JSON.stringify(value));
  fs.writeFileSync(path.join(logs,'instruction.md'),'Execute the echo fixture, then finish.');
  await run(process.execPath,[path.join(bundle.runtime,'src/execution/adapters/quantum_harbor/worker.mjs'),
   logs,bundle.path,path.join(dir,'unused.sock'),String(Date.now()+40000)],
   {cwd:'/tmp',timeout:45000,env:{...process.env,PHYEXP_COMPOSITION_FIXTURE_KEY:'fixture-composition-key',
    PHYEXP_ACCOUNTING_URL:'',PHYEXP_ACCOUNTING_TOKEN:'',PHYEXP_RUNNER_IMAGE_ID:''}});
  if(providerFailure)throw providerFailure;
  const receipt=JSON.parse(fs.readFileSync(path.join(logs,'load-receipt.json')));
  assert.equal(receipt.compositionId,bundle.id);
  assert.equal(receipt.framework.version,recipe.dshVersion);
  assert.equal(receipt.plugins[0].config.prefix,'frozen:');
  const summary=JSON.parse(fs.readFileSync(path.join(logs,'runtime-summary.json')));
  assert.equal(summary.status,'completed');assert.equal(summary.toolCalls,1);assert.equal(requests,3);
  assert.equal(summary.requestRecovery.recoveredRequests,1);assert.equal(summary.failure,null);
  const events=JSON.parse(fs.readFileSync(path.join(logs,'events.json')));
  assert.deepEqual(events.filter(e=>e.type==='plugin:phyexp-request-recovery/scheduled').map(e=>e.data.delayMs),[2000]);
  const config=JSON.parse(fs.readFileSync(path.join(logs,'runner-config/runner.json')));
  assert.deepEqual(config.requestRecovery,recipe.requestRecovery);
  assert.equal(summary.usage.totalTokens,24);
 }finally{
  server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  console.log('Composition worker evidence: '+dir);
 }
});
