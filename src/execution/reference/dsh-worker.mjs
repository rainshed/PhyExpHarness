import {referenceSpec,referenceProvider} from './native.mjs';
import {runExternal} from './worker.mjs';
import fs from 'node:fs';
import {BENCHMARK_STREAM_POLICY} from '../host/stream_guard.mjs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createProviderCredentials} from '../host/provider_auth.mjs';
import {ModelGateway,providerRuntime} from '../host/model_gateway.mjs';
import {isolatedSession} from '../host/isolation.mjs';
import {forwardMcp,callContainer} from '../host/capabilities.mjs';
import {budgetGate} from '../host/budget.mjs';
import {summarizeUsage} from '../host/usage.mjs';
import {verifyToolReceipt} from '../adapters/quantum_harbor/profile.mjs';
import {resolveBundle,pluginMounts} from '../bundle/manifest.mjs';

const [logs,bundleRoot,socketPath,deadlineString]=process.argv.slice(2);
const resolved=resolveBundle(bundleRoot),bundle=resolved.manifest;
const reference=referenceSpec();
if(reference?.harnessRef&&reference.harnessRef!=='dsh-standard'){await runExternal({logs,bundleRoot,socketPath,deadline:Number(deadlineString),reference});process.exit(process.exitCode||0);}
const recipe=JSON.parse(fs.readFileSync(path.join(bundleRoot,'recipe.json')));
if(reference){for(const k of ['provider','model','reasoningEffort','maxTokens','providerConfig'])delete recipe[k];Object.assign(recipe,reference.native?.call||reference.fixedSolver);}
const standard=reference?.harnessRef==='dsh-standard';
const benchmark=recipe.timePolicy==='benchmark-time-v1';
const started=Date.now();const deadline=benchmark?Number(deadlineString):Math.min(Number(deadlineString),started+recipe.agentTimeoutSec*1000);
if(!Number.isFinite(deadline))throw new Error('Explicit finite deadline required');
const connections=JSON.parse(fs.readFileSync(path.join(logs,'mcp-connections.json')));
const summary={status:'running',recipe,model:recipe.model,provider:recipe.provider,bundleId:bundle.id,usage:{},toolCalls:0};
const budget=budgetGate({deadline,softTokenLimit:Number(process.env.PHYEXP_RUN_TOKEN_LIMIT)||Infinity,
 url:process.env.PHYEXP_ACCOUNTING_URL,token:process.env.PHYEXP_ACCOUNTING_TOKEN,purpose:'solver'});
let gateway,session,credentials,provider,checkpoint,watchdog;let terminating=false;
const redact=value=>credentials?credentials.redact(value):String(value);
function save(){
 if(gateway)Object.assign(summary,['completed','error','cancelled'].includes(summary.status)?gateway.persistFinal(summary):gateway.diagnostics(summary));
 const events=session?.messages.filter(m=>m.method==='session.event').map(m=>m.params.event)||[];
 summary.toolCalls=events.filter(e=>e.type==='tool/call').length;
 summary.modelResponses=events.filter(e=>e.type==='assistant/message').length;
 summary.usage=summarizeUsage(events);summary.accounting=budget.snapshot();summary.elapsedSeconds=(Date.now()-started)/1000;
 fs.writeFileSync(path.join(logs,'runtime-summary.json'),redact(JSON.stringify(summary,null,2))+'\n');
 fs.writeFileSync(path.join(logs,'events.json'),redact(JSON.stringify(events))+'\n');return events;
}
async function stop(){if(terminating)return;terminating=true;summary.status='cancelled';save();await session?.dispose();credentials?.dispose();process.exit(143);}
try{
 if(reference){({credentials,provider}=await referenceProvider(reference));}
 else{credentials=createProviderCredentials(recipe,{minimumValidityMs:Math.max(120000,deadline-Date.now()+120000)});
 provider=await providerRuntime({model:recipe,credentialFile:credentials.credentialFile});}
 gateway=new ModelGateway({...(benchmark?{policy:BENCHMARK_STREAM_POLICY}:{}),model:recipe,adapter:provider,deadline,audit:path.join(logs,'gateway-audit.jsonl'),reserve:budget.reserve,settle:budget.settle,redact:credentials.redact});
 const plugins=bundle.plugins.map(p=>({id:p.name,name:'/opt/phyexp/'+p.entry,config:p.config}));
 session=isolatedSession({executionRoot:standard?path.resolve(import.meta.dirname,'..'):resolved.executionRoot,logs,gateway,image:process.env.PHYEXP_RUNNER_IMAGE_ID||bundle.runnerImage,
  config:{standardReference:standard,disableLocalTools:!standard,fixedModel:Object.fromEntries(['provider','model','reasoningEffort','maxTokens'].map(k=>[k,recipe[k]])),modelInfo:provider.info,mcpConnections:connections,
   requestRecovery:recipe.requestRecovery,recoveryDeadline:deadline,
   environment:{PHYEXP_BENCHMARK_TIME:benchmark?'1':'0',PHYEXP_MAX_OUTPUT_CHARS:String(recipe.maxOutputChars),...(standard?{PHYEXP_TASK_TOOL_NAME:'task_bash'}:{})},
   plugins:[{id:'container-tools',name:'/opt/phyexp/src/execution/adapters/quantum_harbor/container_tool.mjs'},...plugins]},
  mounts:pluginMounts(resolved),
  async *handler(op,payload,signal){
   if(op==='mcp')yield* forwardMcp(connections,payload,signal);
   else if(op==='tool')yield await callContainer(socketPath,payload.command,signal,benchmark?deadline:null);
   else if(op==='receipt'){fs.writeFileSync(path.join(logs,payload.kind==='bootstrap'?'bootstrap-receipt.json':'tool-ready.json'),JSON.stringify(payload));yield {ok:true};}
   else throw new Error('Capability denied');
  }});
 process.once('SIGTERM',stop);process.once('SIGINT',stop);
 watchdog=setTimeout(stop,Math.max(1,deadline-Date.now()));checkpoint=setInterval(save,3000);
 summary.initialize=await session.request('initialize',{cwd:'/tmp/work',provider:recipe.provider,model:recipe.model,reasoningEffort:recipe.reasoningEffort,maxTokens:recipe.maxTokens});
 const additionalTools=bundle.plugins.flatMap(p=>p.tools||[]);
 const toolReceipt=standard?JSON.parse(fs.readFileSync(path.join(logs,'tool-ready.json'))):verifyToolReceipt(logs,connections,additionalTools); // Initial receipt precedes candidate plugins; admission checks all request headers below.
 const requiredTools=[...new Set([...toolReceipt.tools,...additionalTools])];
 const instruction=fs.readFileSync(path.join(logs,'instruction.md'),'utf8');
 const environment=JSON.parse(fs.readFileSync(path.join(logs,'environment.json')));
 const timingNote=environment.timing?'\nBenchmark solver time limit: '+environment.timing.solverTimeSeconds+' seconds. Solver deadline (UTC): '+new Date(environment.timing.solverDeadline*1000).toISOString()+'.\n':'';
 const prompt=instruction+timingNote+'\n\nExecution environment (adapter metadata):\n'
  +(standard?'Native tools operate in the isolated Harness workspace. Use task_bash for all task files and final submissions in /app. ':'')+'The '+(standard?'task_bash':'bash')+' tool runs inside the task container, starting in /app on each call. Files persist between calls; shell state does not.\n'
  +'Configured MCP endpoints (reachable from Python client scripts inside the container):\n'+JSON.stringify(environment.mcpServers)+'\n';
 fs.writeFileSync(path.join(logs,'prompt.txt'),prompt);
 fs.writeFileSync(path.join(logs,'load-receipt.json'),JSON.stringify({bundleId:bundle.id,compositionId:bundle.compositionId,framework:bundle.framework,worker:import.meta.url,agent:bundle.agentEntry,plugins:bundle.plugins,filesVerified:Object.keys(bundle.files).length},null,2));
 // Enforce base inventory and declared additions on every call, including calls made by plugins.
 const stream=gateway.stream.bind(gateway);
 gateway.stream=async function*(request,signal){
  const names=(request.tools||[]).map(t=>t.name);
  if(!standard&&((request.sessionId && requiredTools.some(n=>!names.includes(n)))||names.some(n=>!requiredTools.includes(n)&&!additionalTools.includes(n))))throw new Error('Model tool inventory differs from frozen candidate');
  yield*stream(request,signal);
 };
 const events=await session.prompt('solver-'+crypto.randomUUID(),prompt,Math.max(1,deadline-Date.now()));
 summary.turnEnd=events.filter(e=>e.type==='turn/end').at(-1)?.data.reason;summary.exit=await session.shutdown();
 if(summary.exit.code!==0||summary.turnEnd?.kind!=='completed')throw new Error('Runtime did not finish a completed turn');
 summary.status='completed';summary.finalText=events.filter(e=>e.type==='assistant/message').at(-1)?.data.message.content.filter(c=>c.type==='text').map(c=>c.text).join('')||'';
 summary.authentication=credentials.description;summary.reference=reference?{mode:reference.mode,modelRef:reference.modelRef,harnessRef:reference.harnessRef,runtime:reference.runtime}:null;
}catch(error){summary.status='error';summary.error=redact(error.stack||error.message);process.exitCode=1;}
finally{clearInterval(checkpoint);clearTimeout(watchdog);save();credentials?.dispose();
 let cleanupTimer;
 try{await Promise.race([(async()=>{await session?.dispose();await provider?.dispose();})(),new Promise(resolve=>{cleanupTimer=setTimeout(()=>{summary.cleanupTimedOut=true;resolve();},10000)})]);}
 finally{clearTimeout(cleanupTimer);save();}
}

// Provider transports may retain idle sockets; the per-run host owns no work after durable closeout.
process.exit(process.exitCode||0);
