import {channel} from './domain-control.mjs';
export const name='meta-isolated-subagent-adapter';
export const inject=['subagents'];
export function apply(ctx){
 ctx.subagents.registerProvider({name:'meta-isolated',inheritsParentContext:false,
  capabilities:{agentOptions:false,agentPreset:true,outputSchema:true,depthLimit:true},
  async start(request){
   const run=await channel('child_start',{preset:request.agentPreset,prompt:request.prompt,outputSchema:request.outputSchema},request.signal);
   let disposed=false;
   const result=(async()=>{
    while(!disposed){
     const row=await channel('child_status',{id:run.id},request.signal);
     if(row.result)return row.result;
     await new Promise(resolve=>setTimeout(resolve,100));
    }
    return {output:[],stopReason:'aborted'};
   })().catch(error=>({output:[],stopReason:'error',diagnostic:String(error).slice(0,4000)}));
   return {id:run.id,result,async dispose(){if(disposed)return;disposed=true;await channel('child_cancel',{id:run.id},AbortSignal.timeout(5000)).catch(()=>{});}};
  }
 });
}
