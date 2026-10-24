import {appendLog} from './log_store.mjs';
import fs from 'node:fs';
import crypto from 'node:crypto';
import path from 'node:path';
import {StreamGuard,DEFAULT_STREAM_POLICY} from './stream_guard.mjs';
import { Context } from '@deepseek-ai/cordis';
import { LlmRuntime } from '@deepseek-ai/dsh-llm';
import LocalCredentials from '@deepseek-ai/dsh-credentials-local';
import * as PiAi from '@deepseek-ai/dsh-llm-pi-ai';
import * as DeepSeek from '@deepseek-ai/dsh-llm-deepseek-api-key';
import {providerRoute,piAiProfile} from './providers.mjs';
import {classifyModelFailure,RECOVERABLE_REQUEST_FAILURES} from './model_failures.mjs';
import {ADMISSION_CODES} from './budget.mjs';
import {ACCESS_CODES} from './model_access.mjs';
import {TransportDiagnostics} from './transport_diagnostics.mjs';
import {validateJsonSchemaValue} from '@deepseek-ai/dsh-tools';
import {recoveryPolicy,hasStrategy,OUTPUT_FAILURES} from '../recovery/policy.mjs';
const contextOverflow=failure=>failure?.observed?.providerCode==='CONTEXT_WINDOW_EXCEEDED';

// Host storage failures remain authoritative after provider cancellation and
// repeated final saves. Request-level diagnostics retain all secondary facts.
export function hostFailureDiagnostics(summary,diagnostics){
 const host=summary.hostFailure;if(!host)return diagnostics;
 const model=diagnostics.failure;
 // An already-terminal model fault can also precede a later cleanup write error.
 const modelFirst=model&&Date.parse(model.detectedAt)<Date.parse(host.detectedAt);
 const primary=modelFirst?model:host,secondary=modelFirst?host:model;
 const secondaryCodes=[...new Set([...(primary.secondaryCodes||[]),...(secondary?.secondaryCodes||[]),
  ...(secondary&&secondary.code!==primary.code?[secondary.code]:[])])];
 return {...diagnostics,failureContract:'request-failure-v2',failure:{...primary,...(secondaryCodes.length?{secondaryCodes}:{})}};
}

// The trusted caller owns route, deadline, accounting and credentials. Runner input owns none of them.
function bounded(promise,ms){let timer;return Promise.race([promise,new Promise(resolve=>{timer=setTimeout(resolve,ms);})]).finally(()=>clearTimeout(timer));}
function nextOrAbort(iterator,signal){
 return new Promise((resolve,reject)=>{
  const cancelled=()=>reject(new Error('Model call cancelled'));
  if(signal.aborted)return cancelled();
  signal.addEventListener('abort',cancelled,{once:true});
  Promise.resolve().then(()=>iterator.next()).then(resolve,reject).finally(()=>signal.removeEventListener('abort',cancelled));
 });
}
export class ModelGateway {
 constructor({model,adapter,deadline,audit,reserve=async()=>{},settle=async()=>{},policy=DEFAULT_STREAM_POLICY,requestRecovery=null,redact=String}){
  this.model=Object.freeze({...model});this.adapter=adapter;this.deadline=deadline;this.audit=audit;
  this.reserve=reserve;this.settle=settle;this.policy=Object.freeze({...DEFAULT_STREAM_POLICY,...policy});
  this.recovery=recoveryPolicy(requestRecovery);this.recoveryV2=this.recovery?.version==='solver-request-recovery-v2';
  this.recoveryCounts=new Map();
  this.active=new Map();this.requests=new Map();this.firstFailure=null;this.terminalFailure=null;this.stopped=false;this.redact=redact;
 }
 recoverableOutput(failure){return OUTPUT_FAILURES.has(failure.code)&&(hasStrategy(this.recovery,'response-recovery')||
  hasStrategy(this.recovery,'tool-argument-recovery')&&failure.observed?.phase==='tool-feedback');}
 record(event){try{appendLog(this.audit,this.redact(JSON.stringify({time:new Date().toISOString(),...event}))+'\n');}
  catch(error){if(error.hostFailure)this.hostFailure??=error.hostFailure;throw error;}}
 fail(failure){
  this.record({type:'failure',...failure});
  this.firstFailure??=failure;
  const request=this.requests.get(failure.requestId);
  if(request){request.failure=failure;request.failedAt=Date.now();}
  // Native overflow recovery must be able to send its compaction request. This
  // does not add a retry loop or relax fixed-route, budget or deadline checks.
  if(!RECOVERABLE_REQUEST_FAILURES.has(failure.code)&&!this.recoverableOutput(failure)&&!contextOverflow(failure)&&!this.terminalFailure){this.terminalFailure=failure;
   const file=path.join(path.dirname(this.audit),'failure.json');fs.writeFileSync(file+'.tmp',this.redact(JSON.stringify(failure,null,2))+'\n');fs.renameSync(file+'.tmp',file);
  }
 }
 diagnostics({status,turnEnd,hostFailure}={}){
  const error=turnEnd?.error;const request=error?.requestId?this.requests.get(error.requestId):null;
  const last=[...this.requests.values()].at(-1);
  let failure=this.terminalFailure||(turnEnd?.kind==='error'?(request?.failure||
   (last?.failure&&!last.recoveredBy&&last.providerCode===error?.code?last.failure:null)):null);
  const failures=[...this.requests.values()].filter(r=>r.failure);
  const withTransport=f=>{const transport=this.requests.get(f?.requestId)?.transport;
   return f&&transport?{...f,observed:{...f.observed,transport:transport.snapshot()}}:f;};
  failure=withTransport(failure);
  return hostFailureDiagnostics({hostFailure:hostFailure||this.hostFailure},{failureContract:'request-failure-v2',failure:status==='completed'?null:failure,
   requestRecovery:{failedRequests:failures.length,recoveredRequests:failures.filter(r=>r.recoveredBy).length,
    failures:failures.map(r=>({...withTransport(r.failure),...(this.recoveryV2?{recoveryChainId:r.chainId,parentRequestId:r.parentRequestId}:{}),...(r.recoveredBy?{recoveredBy:r.recoveredBy}:{})}))}});
 }
 persistFinal(summary){
  const value=this.diagnostics(summary);const file=path.join(path.dirname(this.audit),'failure.json');
  fs.writeFileSync(file+'.tmp',this.redact(JSON.stringify({schemaVersion:2,...value},null,2))+'\n');fs.renameSync(file+'.tmp',file);
  return value;
 }
 async *stream(request,signal){
  // Recovery references are host-validated control data, never provider input.
  const {phyexpRecovery:recoveryRef,phyexpRecoveryScope:recoveryScope,...providerRequest}=request;request=providerRequest;
  if(this.hostFailure)throw Object.assign(new Error('Host audit unavailable'),{hostFailure:this.hostFailure});
  // Native compaction omits reasoningEffort. Use the operator's fixed value,
  // rather than rejecting the SDK's summary call or falling back at the provider.
  if(request.purpose==='compaction'&&request.reasoningEffort===undefined)
   request={...request,reasoningEffort:this.model.reasoningEffort};
  for(const key of ['provider','model','reasoningEffort','maxTokens'])if(this.model[key]!==undefined&&request[key]!==this.model[key]){
   this.record({type:'rejected',reason:'fixed_model_mismatch',field:key});throw new Error('Fixed model mismatch: '+key);
  }
  if(this.terminalFailure)throw new Error(this.terminalFailure.code);
  if(this.stopped)throw new Error('Gateway cancelled');
  if(signal?.aborted)throw new Error('Model call cancelled');
  if(Date.now()>=this.deadline)throw new Error('Run deadline reached');
  let parent;
  if(recoveryRef){
   parent=this.requests.get(recoveryRef.parentRequestId);
   if(!this.recoveryV2||!parent?.failure||parent.recoveredBy||parent.chainId!==recoveryRef.chainId||
    parent.sessionId!==request.sessionId||(parent.purpose==='compaction')!==(request.purpose==='compaction'))throw new Error('Invalid recovery parent');
   // Independent admission cap: another listener cannot multiply a claimed
   // recovery chain even if it returns retry before the coordinator sees it.
   if(!contextOverflow(parent.failure)){
    const counts=this.recoveryCounts.get(parent.chainId)||{total:0,content:0,transport:0};
    const category=OUTPUT_FAILURES.has(parent.failure.code)?'content':'transport';
    const limit=category==='content'?this.recovery.contentRetryDelaysSeconds.length:this.recovery.retryDelaysSeconds.length;
    if(counts.total>=this.recovery.maxChainRetries||counts[category]>=limit){
     this.record({type:'recovery_stopped',requestId:parent.id,recoveryChainId:parent.chainId,reason:'host_recovery_limit',counts});
     throw Object.assign(new Error('Model recovery limit reached'),{gatewayFailure:{code:'RECOVERY_STOPPED',message:'Model recovery limit reached',requestId:parent.id}});
    }
    this.recoveryCounts.set(parent.chainId,{...counts,total:counts.total+1,[category]:counts[category]+1});
   }
  }
  const id=crypto.randomUUID(),controller=new AbortController();
  const combined=signal?AbortSignal.any([signal,controller.signal]):controller.signal;
  this.active.set(id,controller);
  this.record({type:'admission_started',id});
  const admissionTimer=setTimeout(()=>controller.abort('trial_deadline'),Math.max(1,this.deadline-Date.now()));
  try {
   await this.reserve(id,request,{signal:combined,onState:state=>this.record({type:'admission_'+state.status,id,...state})});
  }catch(error){
   const detail=error.admissionFailure||{};
   const code=controller.signal.reason==='trial_deadline'?'trial_deadline':combined.aborted?'request_cancelled':(ADMISSION_CODES.has(detail.code)||ACCESS_CODES.has(detail.code))?detail.code:'control_unavailable';
   const failure={schemaVersion:1,code,stage:'admission',source:'host-admission',requestId:id,
    detectedAt:new Date().toISOString(),termination:'admission',observed:{...detail}};
   this.record({type:'admission_denied',id,failure});this.fail(failure);
   error.gatewayFailure={code,message:code,requestId:id};
   this.active.delete(id);throw error;
  }finally{clearTimeout(admissionTimer);}
  const {signal:ignoredSignal,...contents}=request;
  const state={id,sessionId:request.sessionId,purpose:request.purpose,chainId:parent?.chainId||id,parentRequestId:parent?.id,
   startedAt:Date.now(),key:crypto.createHash('sha256').update(JSON.stringify(contents)).digest('hex'),toolIssues:[]};
  const transport=new TransportDiagnostics({configuredTransport:this.adapter?.transport,redact:this.redact,
   record:event=>this.record({type:'transport',id,...event})});
  state.transport=transport;
  this.requests.set(id,state);
  const guard=new StreamGuard(this.policy);
  this.active.set(id,controller);let usage=null,finish=null,timeout,idle,iterator,observedFinish=false;
  const failure=(code,observed={})=>{if(state.failure)return state.failure;const f={...guard.fault(code,Date.now(),{...observed,transport:transport.snapshot()}),requestId:id,
   termination:code==='request_cancelled'?'cancelled':code.startsWith('model_')?'provider':'protection'};this.fail(f);return f;};
  const outputFailure=()=>({code:'MODEL_OUTPUT_INVALID',message:'Model returned invalid tool arguments or output',
   outputCode:state.failure.code,requestId:id,recoveryChainId:state.chainId});
  const cancel=code=>{if(!controller.signal.aborted){failure(code);controller.abort(code);}};
  const consume=chunk=>{if(chunk.type==='usage')usage=chunk.usage;if(chunk.type==='finish'){finish=chunk.reason;observedFinish=true;}};
  const drain=async pending=>{let open=true;
   try{await bounded((async()=>{for(let late=await pending;open&&!late.done;late=await transport.run(()=>iterator.next())){
    consume(late.value);this.record({type:'chunk',id,chunk:late.value,afterCancellation:true});if(observedFinish)break;
   }})().catch(()=>{}),this.policy.cleanupGraceMs);}finally{open=false;}
  };
  this.record({type:'request',id,request,streamPolicy:this.policy,...(this.recoveryV2?{recoveryChainId:state.chainId,parentRequestId:state.parentRequestId}:{})});
  const requestLimit=this.policy.requestTimeoutMs??Infinity;
  timeout=setTimeout(()=>cancel(this.deadline<=guard.startedAt+requestLimit?'trial_deadline':'request_timeout'),Math.max(1,Math.min(this.deadline-Date.now(),requestLimit)));
  if(this.policy.streamIdleTimeoutMs!=null)idle=setTimeout(()=>cancel('stream_idle_timeout'),this.policy.streamIdleTimeoutMs);
  try{
   // Admission can await the remote ledger; cancellation/deadline still apply when it returns.
   if(this.stopped||signal?.aborted){failure('request_cancelled');throw new Error('Model call cancelled');}
   if(Date.now()>=this.deadline){failure('trial_deadline');throw new Error('Run deadline reached');}
   iterator=transport.run(()=>this.adapter.stream({...request,signal:combined})[Symbol.asyncIterator]());
   while(true){
    // Retain the actual pending read so a late provider usage receipt can be archived on cancellation.
    const pending=Promise.resolve().then(()=>transport.run(()=>iterator.next()));
    let result;
    try{result=await nextOrAbort({next:()=>pending},combined);}
    catch(error){
     if(combined.aborted)await drain(pending);
     throw error;
    }
    if(result.done)break;
    const chunk=result.value;consume(chunk);this.record({type:'chunk',id,chunk});
    clearTimeout(idle);if(this.policy.streamIdleTimeoutMs!=null)idle=setTimeout(()=>cancel('stream_idle_timeout'),this.policy.streamIdleTimeoutMs);
    let fault=guard.accept(chunk);
    if(!fault&&this.recoveryV2&&chunk.type==='block-end'&&chunk.block?.type==='tool-call'){
     const schema=request.tools?.find(t=>t.name===chunk.block.name)?.parameters;
     if(schema&&validateJsonSchemaValue(schema,JSON.parse(chunk.block.arguments)).length)
      fault=guard.fault('tool_argument_schema_error',Date.now(),{phase:'tool-call-end',callId:chunk.block.id});
    }
    for(const warning of guard.warnings.splice(0))this.record({type:'warning',id,...warning});
    if(fault?.observed?.phase==='tool-call-end'&&chunk.block?.id&&recoveryScope==='step'&&request.purpose!=='compaction'&&hasStrategy(this.recovery,'tool-argument-recovery')){
     state.toolIssues.push({callId:chunk.block.id,code:fault.code,
      message:'Invalid tool arguments: provide a complete JSON object matching the declared tool schema. The tool was not executed.'});
     fault=null; // Still require a successful terminal receipt before accepting this call for error feedback.
    }
    if(fault){this.fail({...fault,requestId:id});controller.abort(fault.code);
     // Wait briefly for a trustworthy late terminal receipt; never execute truncated arguments.
     await drain(Promise.resolve().then(()=>transport.run(()=>iterator.next())));
     throw new Error(fault.code);
    }
    if(chunk.type==='finish'&&finish?.kind==='max-tokens')failure('model_output_limit');
    if(chunk.type==='finish'&&finish?.kind==='aborted')failure('request_cancelled');
    if(chunk.type==='finish'&&finish?.kind==='error'){
     transport.adapterFailure(finish.failure);
     const normalized=classifyModelFailure(finish.failure,transport.failureFacts());failure(normalized.code,normalized.observed);
     state.providerCode=normalized.failure.code;
     finish={...finish,failure:{...normalized.failure,requestId:id,...(this.recoveryV2?{recoveryChainId:state.chainId}:{})}};
     yield {...chunk,reason:finish};
    }else yield chunk;
   }
   if(!finish){failure('model_stream_incomplete');throw new Error('Model stream ended without terminal finish');}
   if(this.recoveryV2&&finish.kind!=='error'&&finish.kind!=='aborted'&&!state.failure){
    if(state.toolIssues.length){failure(state.toolIssues[0].code,{phase:'tool-feedback',callIds:state.toolIssues.map(i=>i.callId)});state.providerCode='MODEL_OUTPUT_INVALID';}
    yield {type:'phyexp-request-outcome',requestId:id,...(state.toolIssues.length?{failure:outputFailure(),issues:state.toolIssues}:{})};
   }
  }catch(error){
   transport.error('adapter_error',error);
   this.record({type:'adapter_error',id,error:{name:error?.name,code:error?.code,message:String(error?.message||error)}});
   const normalized=classifyModelFailure(error,transport.failureFacts());
   if(!state.failure)failure(combined.aborted?'request_cancelled':normalized.code,normalized.observed);
   state.providerCode=this.recoverableOutput(state.failure)?'MODEL_OUTPUT_INVALID':state.failure.code==='model_stream_incomplete'?'TRANSPORT':normalized.failure.code;
   // Carry safe structured facts through the process bridge; arbitrary stack text stays local.
   error.gatewayFailure=this.recoverableOutput(state.failure)?outputFailure():{...normalized.failure,code:RECOVERABLE_REQUEST_FAILURES.has(state.failure.code)||contextOverflow(state.failure)?state.providerCode:state.failure.code,requestId:id,
    ...(this.recoveryV2?{recoveryChainId:state.chainId}:{})};
   throw error;
  }finally{
   clearTimeout(timeout);clearTimeout(idle);controller.abort('Request finished');
   // Detached cleanup cannot delay failure reporting indefinitely.
   if(iterator?.return)void bounded(Promise.resolve(transport.run(()=>iterator.return())).catch(()=>{}),this.policy.cleanupGraceMs);
   transport.finish();
   if(state.failure)state.failure.observed={...state.failure.observed,transport:transport.snapshot()};
   const usageStatus=Number.isFinite(usage?.totalTokens)&&finish&&finish.kind!=='error'?'reported':'unknown';
   this.record({type:'settled',id,usage,finish,usageStatus});
   try{const receipt=await this.settle(id,{usage,finish});if(receipt?.status==='pending')this.record({type:'settlement_pending',id,...receipt});}
   catch(error){this.record({type:'settlement_pending',id,reason:'controller_unavailable'});}
   finally{this.active.delete(id);}
   if(!state.failure&&finish&&finish.kind!=='error'){
    state.completedAt=Date.now();
    for(const prior of this.requests.values()){
     const compacted=contextOverflow(prior.failure)&&state.purpose!=='compaction'&&prior.sessionId===state.sessionId&&[...this.requests.values()].some(r=>r.sessionId===state.sessionId&&r.purpose==='compaction'&&r.completedAt>=prior.failedAt&&r.completedAt<=state.startedAt);
     const linked=parent&&prior.chainId===state.chainId&&prior.sessionId===state.sessionId;
     if(prior.failure&&!prior.recoveredBy&&(linked||(!this.recoveryV2&&prior.key===state.key)||compacted)&&prior.failedAt<=state.startedAt){
      prior.recoveredBy=id;this.record({type:'request_recovered',id:prior.id,recoveredBy:id});
     }
    }
   }
  }
 }
 abort(){this.stopped=true;for(const controller of this.active.values())controller.abort('Supervisor cancelled');}
}

export async function providerRuntime({ model, credentialFile, providerConfig }) {
  const ctx = new Context();
  try {
    await ctx.plugin(LlmRuntime).await();
    await ctx.plugin(LocalCredentials, { path: credentialFile, watch: false }).await();
    const route=providerRoute(model,providerConfig),entry=route.models[0];
    if(route.adapter === 'deepseek') {
      await ctx.plugin(DeepSeek, {baseURL:route.baseURL,apiKeyEnv:route.auth.env,
        models:[{id:entry.id,name:entry.name,contextWindow:entry.contextWindow??1000000,maxTokens:entry.maxTokens??8192,inputModalities:entry.input??['text']}],
        reasoningEffort:model.reasoningEffort, retryPolicy:{mode:'normal',maxRetries:0}}).await();
    } else {
      await ctx.plugin(PiAi, { providers: { [model.provider]: piAiProfile(route) } }).await();
    }
    const info = await ctx.llm.resolveModelInfo(model.provider, model.model);
    return { info, transport:route.transport||(model.provider==='openai-codex'?'auto':'provider-default'),
      stream: request => ctx.llm.stream(request), dispose: () => ctx.fiber.dispose() };
  } catch (error) { await ctx.fiber.dispose(); throw error; }
}
