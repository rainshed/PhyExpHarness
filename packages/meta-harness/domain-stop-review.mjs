import {archiveOutput} from './output-context.mjs';
import {reviewSchema} from './stop-review.mjs';
export const name='meta-stop-review';
export const inject=['tools','metaControl','subagents'];
export function apply(ctx,config){
 ctx.on('tools/pre-execute',async(exec,next)=>{
  if(exec.name!=='campaign_finish'||exec.arguments.condition!=='exhausted')return next();
  await ctx.metaControl.observe(config.pluginId,'triggered',exec);
  let activation;
  try{
   const review=await ctx.metaControl.runtime('review_request',{request:exec.arguments},exec.signal);
   if(review.state==='pending'&&!review.replayed){
    activation=await ctx.subagents.startActivation({provider:'meta-isolated',label:'停止条件独立审查',request:{parent:exec.agent,agentPreset:'phyexp-stop-reviewer',prompt:[{type:'text',text:JSON.stringify(review)}],outputSchema:reviewSchema,maxDepth:1},signal:exec.signal,delivery:'caller'});
    await activation.result;
   }
   // Approval comes only from the host after the isolated child finished. The
   // parent cannot submit a verdict or attach an arbitrary child identity.
   const receipt=await ctx.metaControl.runtime('review_status',{reviewId:review.id},exec.signal);
   if(receipt.state==='approved'){ctx.metaControl.grants.set(exec.token,receipt.id);return next();}
   return {kind:'deny',reason:JSON.stringify({stopReview:receipt,action:'Continue research using the review findings.'})};
  }catch(error){
   const file=await archiveOutput({name:'campaign_finish',stage:'stop-review',error:String(error)});
   return {kind:'deny',reason:JSON.stringify({status:'rejected',summary:'Independent review did not approve; read the diagnostic file.',file})};
  }
  finally{await activation?.dispose();}
 });
}
