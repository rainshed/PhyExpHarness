import {readLogRecordsSync} from '../host/log_store.mjs';
import {hostFailureDiagnostics} from '../host/model_gateway.mjs';
import fs from 'node:fs';
import {BENCHMARK_STREAM_POLICY} from '../host/stream_guard.mjs';
import path from 'node:path';
import {referenceProvider} from './native.mjs';
import {WireGateway,wireBinding} from './wire.mjs';
import {executionAccess} from '../host/model_access.mjs';
import {isolatedSession} from '../host/isolation.mjs';
import {forwardMcp,callContainer} from '../host/capabilities.mjs';
import {resolveBundle} from '../bundle/manifest.mjs';
import {summarizeWireUsage} from '../host/usage.mjs';
export async function runExternal({logs,bundleRoot,socketPath,deadline,reference}){
 const bundle=resolveBundle(bundleRoot).manifest;
 const budget=executionAccess(deadline);
 let runtime,gateway,session,timer,checkpoint;
 const summary={status:'running',bundleId:bundle.id,recipe:JSON.parse(fs.readFileSync(path.join(bundleRoot,'recipe.json'))),reference:{mode:reference.mode,harnessRef:reference.harnessRef,modelRef:reference.modelRef,runtime:reference.runtime},toolCalls:0};
 const benchmark=summary.recipe.timePolicy==='benchmark-time-v1';
 const save=()=>{
  const events=session?.messages.filter(m=>m.method==='reference/event').map(m=>m.params)||[];
  if(budget.snapshot){
   summary.accounting=budget.snapshot();
   const audit=path.join(logs,'gateway-audit.jsonl');
   const receipts=fs.existsSync(audit)?readLogRecordsSync(audit):[];
   summary.usage={...summarizeWireUsage(receipts),totalTokens:summary.accounting.confirmedTokens,accounting:'host gateway confirmed tokens; unknown requests reserved separately'};
  }
  summary.failureContract='request-failure-v2';summary.failure=summary.status==='completed'?null:gateway?.failure||null;
  summary.hostFailure??=session?.failure||gateway?.hostFailure;
  Object.assign(summary,hostFailureDiagnostics(summary,{failure:summary.failure}));
  summary.toolCalls=events.reduce((n,e)=>n+(e.type==='item.completed'&&e.item?.type==='mcp_tool_call'?1:e.type==='assistant'?e.message?.content?.filter(c=>c.type==='tool_use').length||0:0),0);
  const redact=runtime?.credentials.redact||String;
  fs.writeFileSync(path.join(logs,'runtime-summary.json'),redact(JSON.stringify(summary,null,2)));
  fs.writeFileSync(path.join(logs,'failure.json'),redact(JSON.stringify({schemaVersion:2,failureContract:summary.failureContract,failure:summary.failure})));
  fs.writeFileSync(path.join(logs,'events.json'),redact(JSON.stringify(events)));
 };
 const stop=()=>{summary.status='cancelled';gateway?.abort();session?.dispose();};
 try{
  runtime=await referenceProvider(reference);summary.model=runtime.model.model;summary.provider=runtime.model.provider;
  gateway=new WireGateway({...(benchmark?{policy:BENCHMARK_STREAM_POLICY}:{}),binding:wireBinding(runtime,reference.harnessRef),budget,deadline,audit:path.join(logs,'gateway-audit.jsonl'),redact:runtime.credentials.redact});
  const connections=JSON.parse(fs.readFileSync(path.join(logs,'mcp-connections.json')));
  const timing=JSON.parse(fs.readFileSync(path.join(logs,'environment.json'))).timing;
  const timingNote=timing?'\nBenchmark solver time limit: '+timing.solverTimeSeconds+' seconds. Solver deadline (UTC): '+new Date(timing.solverDeadline*1000).toISOString()+'.\n':'';
  const prompt=fs.readFileSync(path.join(logs,'instruction.md'),'utf8')+timingNote+'\n\nTask execution boundary: use the task MCP task_bash tool for commands, files and final submissions in the official task container /app. Native file and shell tools operate only in your separate scratch workspace. Task MCP tools are also attached. No prior task session or Meta context is supplied.';
  fs.writeFileSync(path.join(logs,'prompt.txt'),prompt);
  fs.writeFileSync(path.join(logs,'load-receipt.json'),JSON.stringify({bundleId:bundle.id,reference:summary.reference,model:runtime.model,framework:reference.harnessRef,plugins:[],isolation:'network-none; host-only credentials; task command bridge'}));
  session=isolatedSession({executionRoot:path.resolve(import.meta.dirname,'..'),logs,image:process.env.PHYEXP_RUNNER_IMAGE_ID,
   entry:'/opt/phyexp/src/execution/reference/isolated.mjs',gateway,
   config:{harness:reference.harnessRef,fixedModel:Object.fromEntries(['provider','model','reasoningEffort','maxTokens'].filter(k=>runtime.model[k]!==undefined).map(k=>[k,runtime.model[k]])),mcpConnections:connections,prompt},
   async *handler(op,payload,signal){
    if(op==='wire')yield*gateway.stream(payload,signal);
    else if(op==='mcp')yield*forwardMcp(connections,payload,signal);
    else if(op==='tool')yield await callContainer(socketPath,payload.command,signal,benchmark?deadline:null);
    else throw new Error('Reference capability unavailable');
   }});
  process.once('SIGTERM',stop);process.once('SIGINT',stop);timer=setTimeout(stop,Math.max(1,deadline-Date.now()));checkpoint=setInterval(save,3000);
  const exit=await session.exited;save();
  const events=session.messages.filter(m=>m.method==='reference/event').map(m=>m.params);
  const terminal=events.findLast(e=>e.type==='result'||e.type==='turn.completed'||e.type==='turn.failed');
  if(exit.code!==0||!terminal||terminal.is_error||terminal.type==='turn.failed')throw new Error('Reference Harness did not complete successfully');
  summary.status='completed';summary.finalText=terminal.result||events.findLast(e=>e.item?.type==='agent_message')?.item?.text||'';
 }catch(error){summary.status=summary.status==='cancelled'?'cancelled':'error';summary.error=runtime?.credentials.redact(error.stack)||String(error);process.exitCode=1;}
 finally{clearTimeout(timer);clearInterval(checkpoint);process.off('SIGTERM',stop);process.off('SIGINT',stop);save();await session?.dispose();await runtime?.provider.dispose();runtime?.credentials.dispose();}
}
