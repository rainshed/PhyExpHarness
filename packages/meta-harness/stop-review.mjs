export const name='meta-stop-review';
export const inject=['tools','metaControl','subagents'];
export const reviewSchema={type:'object',additionalProperties:false,required:['verdict','reason','evidenceRefs','missingEvidence','nextDirections'],properties:{
 verdict:{type:'string',enum:['approve','continue','insufficient_evidence']},
 reason:{type:'string'},evidenceRefs:{type:'array',items:{type:'string'}},
 missingEvidence:{type:'array',items:{type:'string'}},nextDirections:{type:'array',items:{type:'string'}}
}};
export function apply(ctx,config){
 ctx.on('tools/pre-execute',async (exec,next)=>{
  if(exec.name!=='campaign_finish')return next();
  const input=JSON.parse(exec.arguments.input);
  if(input.condition==='stable')return next();
  if(input.condition!=='exhausted')return {kind:'deny',reason:'Choose stable or exhausted; resource stops are controlled by the platform.'};
  await ctx.metaControl.observe(config.pluginId,'triggered',exec);
  const review=await ctx.metaControl.runtime('review_request',{...ctx.metaControl.actor(exec.agent),request:input},exec.signal);
  if(review.state!=='pending'||review.replayed){
   if(review.state==='approved'){ctx.metaControl.grants.set(exec.token,review.id);return next();}
   return {kind:'deny',reason:JSON.stringify({stopReview:review,action:'Continue exploration; obtain new evidence before another request.'})};
  }
  let activation;const abort=new AbortController();const signal=AbortSignal.any([exec.signal,abort.signal]);
  const timer=setTimeout(()=>abort.abort(new Error('Stop review timeout')),Math.max(1,(config.timeoutSeconds??300)*1000));
  const dispose=()=>{void activation?.dispose();};signal.addEventListener('abort',dispose,{once:true});
  try{
   activation=await ctx.subagents.startActivation({provider:'spawn',label:'停止条件独立审查',request:{parent:exec.agent,agentPreset:'phyexp-stop-reviewer',prompt:[{type:'text',text:JSON.stringify(review)}],outputSchema:reviewSchema,maxDepth:1},signal,delivery:'caller'});
   await ctx.metaControl.runtime('review_attach',{reviewId:review.id,childId:activation.childId},signal);
   if(signal.aborted){await activation.dispose();throw signal.reason;}
   const result=await activation.result;
   if(signal.aborted)throw signal.reason;
   const receipt=await ctx.metaControl.runtime('review_result',{reviewId:review.id,childId:activation.childId,result:result.structured,stopReason:result.stopReason},signal);
   if(receipt.state==='approved'){ctx.metaControl.grants.set(exec.token,receipt.id);return next();}
   return {kind:'deny',reason:JSON.stringify({stopReview:receipt,action:'Continue exploration using the review feedback.'})};
  }catch(error){
   await ctx.metaControl.runtime('review_failed',{reviewId:review.id,error:String(error)},AbortSignal.timeout(5000)).catch(()=>{});
   return {kind:'deny',reason:'Stop review failed; no approval granted. '+String(error)};
  }finally{clearTimeout(timer);signal.removeEventListener('abort',dispose);await activation?.dispose();}
 });
}
