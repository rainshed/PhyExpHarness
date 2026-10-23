import {z} from 'zod';
import {LlmError} from '@deepseek-ai/dsh-llm';
import {appendPluginRecord} from '@deepseek-ai/dsh-session';

const recordPrefix='plugin:phyexp-request-recovery/';
const projectionKey='phyexpRequestRecovery';
export function recoveryPolicy(value){
 if(value==null)return null; // Old frozen recipes and Meta keep their own policy.
 if(value.version!=='solver-request-recovery-v1'||!Array.isArray(value.retryDelaysSeconds)||
  value.retryDelaysSeconds.length!==5||value.retryDelaysSeconds.some(n=>!Number.isFinite(n)||n<=0||n>3600))
  throw new Error('Invalid Solver request recovery policy');
 return Object.freeze({...value,retryDelaysSeconds:Object.freeze([...value.retryDelaysSeconds])});
}
export function retryPlan(policy,previous,failure,deadline,now=Date.now()){
 if(!policy||!recoverableFailure(failure))return {stop:'ineligible'};
 if(previous>=policy.retryDelaysSeconds.length)return {stop:'exhausted'};
 const serverDelay=failure.providerRetryAfterMs;
 const delayMs=Math.max(policy.retryDelaysSeconds[previous]*1000,
  Number.isFinite(serverDelay)&&serverDelay>0?serverDelay:0);
 if(now+delayMs>=deadline)return {stop:'deadline'};
 return {retry:previous+1,delayMs};
}
function recoverableFailure(failure){
 return failure?.code==='TRANSPORT'||failure?.code==='SERVER'&&
  (failure.status===503||failure.message==='Model service overloaded');
}
export function recoveryState(state,event){
 if(event.type==='turn/end')return {step:0,compaction:0};
 if(event.type==='step/start')return {...state,step:0};
 if(event.type==='compaction/start')return {...state,compaction:0};
 if(event.type===recordPrefix+'scheduled')return {...state,[event.data.purpose]:event.data.retry};
 return state;
}
export function cancellableDelay(ms,signal){
 if(signal.aborted)return Promise.resolve(false);
 return new Promise(resolve=>{
  const finish=value=>{clearTimeout(timer);signal.removeEventListener('abort',abort);resolve(value);};
  const abort=()=>finish(false),timer=setTimeout(()=>finish(true),ms);
  signal.addEventListener('abort',abort,{once:true});
 });
}

// A summary is an atomic replacement of context: discard an unsuccessful
// attempt completely, including its usage chunks, before requesting it again.
// Actual usage for every attempt is retained by the trusted host gateway.
export async function* recoverCompaction(stream,options,retry){
 while(true){
  const chunks=[];let bytes=0,failure,finished=false;
  try{
   for await(const chunk of stream(options)){
    bytes+=Buffer.byteLength(JSON.stringify(chunk));
    if(bytes>32*1024*1024)throw new Error('Oversized compaction response');
    chunks.push(chunk);
    if(chunk.type==='finish'){
     finished=true;
     if(chunk.reason.kind==='error')failure=chunk.reason.failure;
    }
   }
   if(failure)throw new LlmError(failure.message,failure.code,failure);
   if(!finished)throw new LlmError('Compaction stream ended without terminal finish','TRANSPORT');
  }catch(error){
   if(await retry(error.failure))continue;
   throw error;
  }
  yield* chunks;return;
 }
}

export function installRequestRecovery(ctx,policy,deadline){
 if(!Number.isFinite(deadline))throw new Error('Solver recovery requires the original finite trial deadline');
 ctx.sessionProjections.register({key:projectionKey,stateVersion:1,
  stateSchema:z.object({step:z.number().int().nonnegative(),compaction:z.number().int().nonnegative()}),
  init:()=>({step:0,compaction:0}),apply:recoveryState});
 const lifetime=new AbortController(),active=new Set();
 const track=operation=>{const pending=operation.finally(()=>active.delete(pending));active.add(pending);return pending;};
 async function retry(session,purpose,failure,signal,location={}){
  const combined=AbortSignal.any([...(signal?[signal]:[]),lifetime.signal]);
  if(combined.aborted)return false;
  const previous=ctx.sessionProjections.stateOf(session,projectionKey)[purpose];
  const plan=retryPlan(policy,previous,failure,deadline);
  const record=(phase,data)=>appendPluginRecord(session,recordPrefix+phase,{policy:policy.version,purpose,...location,...data});
  if(plan.stop){
   if(plan.stop!=='ineligible')record('stopped',{reason:plan.stop,retries:previous,failure});
   return false;
  }
  const data={...plan,failure};record('scheduled',data);
  if(!await cancellableDelay(plan.delayMs,combined)||Date.now()>=deadline){
   record('stopped',{reason:combined.aborted?'cancelled':'deadline',retries:plan.retry,failure});return false;
  }
  record('started',data);return true;
 }
 const dispose=ctx.on('agent/request-error',(payload,next)=>{
  if(!recoverableFailure(payload.failure))return next();
  // Own this chain through exhaustion; candidate handlers cannot multiply it.
  return track(retry(payload.agent.session,'step',payload.failure,payload.signal,
   {turn:payload.turn,step:payload.step}).then(ok=>ok?{kind:'retry'}:undefined));
 });
 ctx.effect(()=>async()=>{dispose();lifetime.abort();await Promise.allSettled([...active]);},'Solver request recovery: cancel waits');
 return (stream,options)=>{
  const session=ctx.agents.get(options.sessionId)?.session;
  if(!session)throw new Error('Compaction recovery requires an attached session');
  return recoverCompaction(stream,options,failure=>track(retry(session,'compaction',failure,options.signal)));
 };
}
