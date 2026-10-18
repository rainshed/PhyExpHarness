import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createChatGPTCredentials} from '../../host/chatgpt_auth.mjs';
import {ModelGateway,providerRuntime} from '../../host/model_gateway.mjs';
import {isolatedSession} from '../../host/isolation.mjs';
import {forwardMcp,callContainer} from '../../host/capabilities.mjs';
import {budgetGate} from '../../host/budget.mjs';
import {summarizeUsage} from '../../host/usage.mjs';
import {verifyToolReceipt} from './profile.mjs';

const [logs,bundleRoot,socketPath,deadlineString]=process.argv.slice(2);
const bundle=JSON.parse(fs.readFileSync(path.join(bundleRoot,'bundle.json')));
const recipe=JSON.parse(fs.readFileSync(path.join(bundleRoot,'recipe.json')));
const started=Date.now();const deadline=Math.min(Number(deadlineString),started+recipe.agentTimeoutSec*1000);
if(!Number.isFinite(deadline))throw new Error('Explicit finite deadline required');
for(const [relative,digest] of Object.entries(bundle.files)){
 const target=path.join(bundleRoot,relative);
 if(fs.lstatSync(target).isSymbolicLink()||crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex')!==digest)throw new Error('Bundle integrity mismatch: '+relative);
}
const connections=JSON.parse(fs.readFileSync(path.join(logs,'mcp-connections.json')));
const summary={status:'running',recipe,model:recipe.model,provider:recipe.provider,bundleId:bundle.id,usage:{},toolCalls:0};
const budget=budgetGate({deadline,softTokenLimit:Number(process.env.PHYEXP_RUN_TOKEN_LIMIT)||Infinity,
 url:process.env.PHYEXP_ACCOUNTING_URL,token:process.env.PHYEXP_ACCOUNTING_TOKEN,purpose:'solver'});
let session,credentials,provider,checkpoint,watchdog;let terminating=false;
const redact=value=>credentials?credentials.redact(value):String(value);
function save(){
 const events=session?.messages.filter(m=>m.method==='session.event').map(m=>m.params.event)||[];
 summary.toolCalls=events.filter(e=>e.type==='tool/call').length;
 summary.modelResponses=events.filter(e=>e.type==='assistant/message').length;
 summary.usage=summarizeUsage(events);summary.accounting=budget.snapshot();summary.elapsedSeconds=(Date.now()-started)/1000;
 fs.writeFileSync(path.join(logs,'runtime-summary.json'),redact(JSON.stringify(summary,null,2))+'\n');
 fs.writeFileSync(path.join(logs,'events.json'),redact(JSON.stringify(events))+'\n');return events;
}
async function stop(){if(terminating)return;terminating=true;summary.status='cancelled';save();await session?.dispose();credentials?.dispose();process.exit(143);}
try{
 credentials=createChatGPTCredentials({minimumValidityMs:Math.max(120000,deadline-Date.now()+120000)});
 provider=await providerRuntime({model:recipe,credentialFile:credentials.credentialFile});
 const gateway=new ModelGateway({model:recipe,adapter:provider,deadline,audit:path.join(logs,'gateway-audit.jsonl'),reserve:budget.reserve,settle:budget.settle});
 const plugins=bundle.plugins.map(p=>({id:p.name,name:'/opt/phyexp/'+p.entry,config:p.config}));
 session=isolatedSession({executionRoot:path.join(bundleRoot,'src/execution'),logs,gateway,image:process.env.PHYEXP_RUNNER_IMAGE_ID||bundle.runnerImage,
  config:{disableLocalTools:true,fixedModel:Object.fromEntries(['provider','model','reasoningEffort','maxTokens'].map(k=>[k,recipe[k]])),modelInfo:provider.info,mcpConnections:connections,
   environment:{PHYEXP_MAX_OUTPUT_CHARS:String(recipe.maxOutputChars)},
   plugins:[{id:'container-tools',name:'/opt/phyexp/src/execution/adapters/quantum_harbor/container_tool.mjs'},...plugins]},
  mounts:bundle.plugins.length?[`type=bind,source=${path.join(bundleRoot,'plugins')},target=/opt/phyexp/plugins,readonly`]:[],
  async *handler(op,payload,signal){
   if(op==='mcp')yield* forwardMcp(connections,payload,signal);
   else if(op==='tool')yield await callContainer(socketPath,payload.command,signal);
   else if(op==='receipt'){fs.writeFileSync(path.join(logs,payload.kind==='bootstrap'?'bootstrap-receipt.json':'tool-ready.json'),JSON.stringify(payload));yield {ok:true};}
   else throw new Error('Capability denied');
  }});
 process.once('SIGTERM',stop);process.once('SIGINT',stop);
 watchdog=setTimeout(stop,Math.max(1,deadline-Date.now()));checkpoint=setInterval(save,3000);
 summary.initialize=await session.request('initialize',{cwd:'/tmp/work',provider:recipe.provider,model:recipe.model,reasoningEffort:recipe.reasoningEffort,maxTokens:recipe.maxTokens});
 const additionalTools=bundle.plugins.flatMap(p=>p.tools||[]);
 const toolReceipt=verifyToolReceipt(logs,connections,additionalTools); // Initial receipt precedes candidate plugins; admission checks all request headers below.
 const requiredTools=[...new Set([...toolReceipt.tools,...additionalTools])];
 const instruction=fs.readFileSync(path.join(logs,'instruction.md'),'utf8');
 const environment=JSON.parse(fs.readFileSync(path.join(logs,'environment.json')));
 const prompt=instruction+'\n\nExecution environment (adapter metadata):\n'
  +'The bash tool runs inside the task container, starting in /app on each call. Files persist between calls; shell state does not.\n'
  +'Configured MCP endpoints (reachable from Python client scripts inside the container):\n'+JSON.stringify(environment.mcpServers)+'\n';
 fs.writeFileSync(path.join(logs,'prompt.txt'),prompt);
 fs.writeFileSync(path.join(logs,'load-receipt.json'),JSON.stringify({bundleId:bundle.id,worker:import.meta.url,agent:bundle.agentEntry,plugins:bundle.plugins,filesVerified:Object.keys(bundle.files).length},null,2));
 // Enforce base inventory and declared additions on every call, including calls made by plugins.
 const stream=gateway.stream.bind(gateway);
 gateway.stream=async function*(request,signal){
  const names=(request.tools||[]).map(t=>t.name);
  if((request.sessionId && requiredTools.some(n=>!names.includes(n)))||names.some(n=>!requiredTools.includes(n)&&!additionalTools.includes(n)))throw new Error('Model tool inventory differs from frozen candidate');
  yield*stream(request,signal);
 };
 const events=await session.prompt('solver-'+crypto.randomUUID(),prompt,Math.max(1,deadline-Date.now()));
 summary.exit=await session.shutdown();summary.turnEnd=events.filter(e=>e.type==='turn/end').at(-1)?.data.reason;
 if(summary.exit.code!==0||summary.turnEnd?.kind!=='completed')throw new Error('Runtime did not finish a completed turn');
 summary.status='completed';summary.finalText=events.filter(e=>e.type==='assistant/message').at(-1)?.data.message.content.filter(c=>c.type==='text').map(c=>c.text).join('')||'';
 summary.authentication=credentials.description;
}catch(error){summary.status='error';summary.error=redact(error.stack||error.message);process.exitCode=1;}
finally{clearInterval(checkpoint);clearTimeout(watchdog);save();credentials?.dispose();
 let cleanupTimer;
 try{await Promise.race([(async()=>{await session?.dispose();await provider?.dispose();})(),new Promise(resolve=>{cleanupTimer=setTimeout(()=>{summary.cleanupTimedOut=true;resolve();},10000)})]);}
 finally{clearTimeout(cleanupTimer);save();}
}

// Provider transports may retain idle sockets; the per-run host owns no work after durable closeout.
process.exit(process.exitCode||0);
