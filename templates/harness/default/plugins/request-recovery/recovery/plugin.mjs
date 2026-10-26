// Ordinary candidate plugin. Meta may edit, replace or omit the entire composition.
import crypto from 'node:crypto';
import {LlmError} from '@deepseek-ai/dsh-llm';
import {StreamGuard,BENCHMARK_STREAM_POLICY} from '../host/stream_guard.mjs';
import {installRecoveryComposition} from './composition.mjs';
import {recoveryPolicy} from './policy.mjs';
export const name='candidate-recovery';
export const inject=['llm','agents','sessionProjections','tools'];
export async function apply(ctx,{policy,runtimeContext}){
 policy=recoveryPolicy(policy);
 const deadline=runtimeContext.deadline*1000;
 const coordinator=await installRecoveryComposition(ctx,policy,deadline);
 const protect=async function*(next,options){
  const id=crypto.randomUUID(),chain=options.phyexpRecovery?.chainId||id;
  const guard=new StreamGuard(BENCHMARK_STREAM_POLICY);let finish;
  const failure=(code,message,extra={})=>({code,message,requestId:id,recoveryChainId:chain,...extra});
  try{
   for await(const chunk of next()){
    const fault=guard.accept(chunk);
    if(fault){const detail=failure('MODEL_OUTPUT_INVALID','Model returned invalid output',{outputCode:fault.code});
     throw Object.assign(new LlmError(detail.message,detail.code,detail),{gatewayFailure:detail});}
    if(chunk.type==='finish')finish=chunk;else yield chunk;
   }
   if(finish?.reason.kind==='error'){
    const detail=failure(finish.reason.failure?.code||'TRANSPORT',finish.reason.failure?.message||'Request failed',finish.reason.failure);
    detail.requestId=id;detail.recoveryChainId=chain;
    yield {type:'finish',reason:{...finish.reason,failure:detail}};return;
   }
   if(!finish){const detail=failure('TRANSPORT','Provider stream ended without a finish event');
    throw Object.assign(new LlmError(detail.message,detail.code,detail),{gatewayFailure:detail});}
   yield {type:'phyexp-request-outcome',requestId:id,failure:null,issues:[]};yield finish;
  }catch(error){
   const detail=error.gatewayFailure||failure(error.code||'TRANSPORT',error.message||'Request failed',error.failure||{});
   // A middleware exception bypasses the native request-error hook. Report a
   // failed request through the stream protocol so the coordinator can act.
   yield {type:'finish',reason:{kind:'error',failure:detail}};
  }
 };
 ctx.on('llm/stream',(options,next)=>coordinator.stream(request=>protect(next,request),options));
}
