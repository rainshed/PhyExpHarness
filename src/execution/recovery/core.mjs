import {Service} from '@deepseek-ai/cordis';
import {z} from 'zod';
import {LlmError,isAgentLoopRequest} from '@deepseek-ai/dsh-llm';
import {appendPluginRecord} from '@deepseek-ai/dsh-session';
import {cancellableDelay,recoverCompaction} from '../runner/request_recovery.mjs';

export const recordPrefix='plugin:phyexp-request-recovery/';
export const projectionKey='phyexpRecoveryV2';
const empty=()=>({step:null,compaction:null});
const chainSchema=z.object({id:z.string(),transport:z.number().int().nonnegative(),content:z.number().int().nonnegative(),total:z.number().int().nonnegative(),
 lastRequestId:z.string(),failure:z.record(z.string(),z.unknown()),issues:z.array(z.object({callId:z.string(),code:z.string(),message:z.string()})),
 pendingFeedback:z.boolean(),stopped:z.string().optional()}).nullable();
export function recoveryState(state,event){
 if(!event.type.startsWith(recordPrefix)||event.data?.policy!=='solver-request-recovery-v2')return state;
 const {purpose}=event.data;if(!['step','compaction'].includes(purpose))return state;
 if(event.type===recordPrefix+'healthy')return {...state,[purpose]:null};
 if(event.type===recordPrefix+'state')return {...state,[purpose]:event.data.chain};
 return state;
}
export function recoveryPlan(policy,chain,strategy,failure,deadline,now=Date.now()){
 if(chain.stopped)return {stop:chain.stopped};
 if(chain.total>=policy.maxChainRetries)return {stop:'chain_exhausted'};
 const delays=strategy.category==='transport'?policy.retryDelaysSeconds:policy.contentRetryDelaysSeconds;
 const count=chain[strategy.category];
 if(count>=delays.length)return {stop:'exhausted'};
 const serverDelay=strategy.category==='transport'?failure.providerRetryAfterMs:0;
 const delayMs=Math.max(delays[count]*1000,Number.isFinite(serverDelay)&&serverDelay>0?serverDelay:0);
 if(now+delayMs>=deadline)return {stop:'deadline'};
 return {retry:count+1,chainRetry:chain.total+1,delayMs};
}

export default class RecoveryCore extends Service{
 static name='recovery-core';
 static inject=['agents','sessionProjections'];
 constructor(ctx,{policy,deadline}){
  super(ctx,'phyexpRecovery');
  if(!Number.isFinite(deadline))throw new Error('Solver recovery requires the original finite trial deadline');
  this.policy=policy;this.deadline=deadline;this.strategies=new Map();this.lifetime=new AbortController();this.active=new Set();
  ctx.sessionProjections.register({key:projectionKey,stateVersion:1,
   stateSchema:z.object({step:chainSchema,compaction:chainSchema}),init:empty,apply:recoveryState});
  ctx.on('agent/request-error',(payload,next)=>{
   if(payload.failure?.code==='RECOVERY_STOPPED')return Promise.resolve(undefined);
   const saved=this.state(payload.agent.session,'step')?.failure;
   const failure=saved?.requestId===payload.failure?.requestId?saved:payload.failure;
   const strategy=this.choose(failure,'request');
   if(!strategy)return next();
   // Exhaustion never delegates the same fault to another retry listener.
   return this.track(this.retry(payload.agent.session,'step',failure,payload.signal,strategy)
    .then(ok=>ok?{kind:'retry'}:undefined));
  },{prepend:true});
  ctx.effect(()=>async()=>{this.lifetime.abort();await Promise.allSettled([...this.active]);},'Recovery: cancel waits');
 }
 register(strategy){
  if(this.strategies.has(strategy.id)||!this.policy.strategies.includes(strategy.id))throw new Error('Invalid recovery strategy registration: '+strategy.id);
  this.strategies.set(strategy.id,strategy);return()=>this.strategies.delete(strategy.id);
 }
 describe(){return {version:this.policy.version,coordinator:'recovery-core',strategies:[...this.strategies.keys()],maxChainRetries:this.policy.maxChainRetries};}
 choose(failure,mode){
  const matches=[...this.strategies.values()].filter(s=>s.matches(failure,mode));
  if(matches.length>1)throw new Error('Ambiguous recovery strategies');
  return matches[0];
 }
 track(operation){const pending=operation.finally(()=>this.active.delete(pending));this.active.add(pending);return pending;}
 state(session,purpose){return this.ctx.sessionProjections.stateOf(session,projectionKey)[purpose];}
 record(session,purpose,phase,data){appendPluginRecord(session,recordPrefix+phase,{policy:this.policy.version,purpose,...data});}
 save(session,purpose,chain){this.record(session,purpose,'state',{chain});return chain;}
 observe(session,purpose,failure,issues=[]){
  const current=this.state(session,purpose),id=failure.recoveryChainId||failure.requestId;
  if(!id)throw new Error('Recovery requires a trusted request identity');
  if(current&&current.id!==id)throw new Error('Recovery chain identity changed without healthy progress');
  return this.save(session,purpose,{...(current||{id,transport:0,content:0,total:0}),lastRequestId:failure.requestId,
   failure,issues,pendingFeedback:issues.length>0});
 }
 async retry(session,purpose,failure,signal,strategy){
  let chain=this.observe(session,purpose,failure);
  const combined=AbortSignal.any([...(signal?[signal]:[]),this.lifetime.signal]);
  const plan=combined.aborted?{stop:'cancelled'}:recoveryPlan(this.policy,chain,strategy,failure,this.deadline);
  const detail={strategy:strategy.id,action:strategy.action,recoveryChainId:chain.id,requestId:failure.requestId,failure,...plan};
  if(plan.stop){this.save(session,purpose,{...chain,stopped:plan.stop});this.record(session,purpose,'stopped',{...detail,reason:plan.stop});return false;}
  chain=this.save(session,purpose,{...chain,[strategy.category]:plan.retry,total:plan.chainRetry,pendingFeedback:false});
  this.record(session,purpose,'scheduled',detail);
  if(!await cancellableDelay(plan.delayMs,combined)||Date.now()>=this.deadline){
   const reason=combined.aborted?'cancelled':'deadline';this.save(session,purpose,{...chain,stopped:reason});
   this.record(session,purpose,'stopped',{...detail,reason});return false;
  }
  this.record(session,purpose,'started',detail);return true;
 }
 stopped(chain){return new LlmError('Model recovery stopped','RECOVERY_STOPPED',{
  code:'RECOVERY_STOPPED',message:'Model recovery stopped',requestId:chain?.lastRequestId,recoveryChainId:chain?.id,recoveryStop:chain?.stopped});}
 async *attempt(stream,options){
  const session=this.ctx.agents.get(options.sessionId)?.session;
  if(!session)throw new Error('Recovery requires an attached session');
  const purpose=options.purpose==='compaction'?'compaction':'step';
  let chain=this.state(session,purpose);
  if(chain?.stopped)throw this.stopped(chain);
  if(chain?.pendingFeedback){
   const strategy=this.choose(chain.failure,'feedback');
   if(!strategy||!await this.track(this.retry(session,purpose,chain.failure,options.signal,strategy)))throw this.stopped(this.state(session,purpose));
   chain=this.state(session,purpose);
  }
  const request={...options,phyexpRecoveryScope:purpose,...(chain?{phyexpRecovery:{chainId:chain.id,parentRequestId:chain.lastRequestId}}:{})};
  let outcome,finish;
  try{
   for await(const chunk of stream(request)){
    if(chunk.type==='phyexp-request-outcome')outcome=chunk;
    else if(chunk.type==='finish')finish=chunk;
    else yield chunk;
   }
  }catch(error){
   // The SDK keeps only its declared LlmFailure fields. Persist host facts
   // before normalization, and join the hook's failure by exact request ID.
   if(error.gatewayFailure&&(this.choose(error.gatewayFailure,'request')||chain&&chain.id===error.gatewayFailure.recoveryChainId))this.observe(session,purpose,error.gatewayFailure);
   throw error;
  }
  if(finish?.reason.kind==='error'&&(this.choose(finish.reason.failure,'request')||chain&&chain.id===finish.reason.failure?.recoveryChainId))this.observe(session,purpose,finish.reason.failure);
  if(finish&&finish.reason.kind!=='error'&&finish.reason.kind!=='aborted'&&outcome){
   if(outcome.failure)this.observe(session,purpose,outcome.failure,outcome.issues);
   else this.record(session,purpose,'healthy',{requestId:outcome.requestId,recoveryChainId:chain?.id||null});
  }
  if(finish)yield finish;
 }
 stream(stream,options){
  if(options.purpose!=='compaction'&&!isAgentLoopRequest(options))return this.direct(stream,options);
  const attempt=request=>this.attempt(stream,request);
  if(options.purpose!=='compaction')return attempt(options);
  const session=this.ctx.agents.get(options.sessionId)?.session;
  if(!session)throw new Error('Compaction recovery requires an attached session');
  return recoverCompaction(attempt,options,failure=>{
   const saved=this.state(session,'compaction')?.failure;
   const actual=saved?.requestId===failure?.requestId?saved:failure;
   const strategy=this.choose(actual,'request');
   return strategy?this.track(this.retry(session,'compaction',actual,options.signal,strategy)):false;
  });
 }
 async *direct(stream,options){
  // Auxiliary calls do not consume or clear the agent loop's recovery chain.
  for await(const chunk of stream({...options,phyexpRecoveryScope:'direct'}))if(chunk.type!=='phyexp-request-outcome')yield chunk;
 }
}
