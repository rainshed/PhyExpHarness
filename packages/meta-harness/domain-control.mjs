import {Service} from '@deepseek-ai/cordis';
import {randomUUID} from 'node:crypto';
import {setTimeout as delay} from 'node:timers/promises';
export async function channel(action,input,signal){
 const response=await fetch(process.env.PHYEXP_GATEWAY_URL+'/meta',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action,input}),signal});
 if(!response.ok)throw new Error(`Meta channel unavailable (${response.status})`);
 const rows=(await response.text()).trim().split('\n').filter(Boolean).map(JSON.parse);
 const error=rows.find(r=>r.error);if(error)throw new Error(error.error);
 return rows.map(r=>r.result).at(-1);
}
// No role credentials in this process. The outside host binds every message to its container.
export default class MetaControl extends Service{
 static inject=['agentPresets','tools','sessionProjections'];
 constructor(ctx,config){
  super(ctx,'metaControl');this.grants=new WeakMap();
  if(config.preset==='phyexp-meta')ctx.on('user-questions/request',async request=>{
   const input={callId:request.wait?.callId||randomUUID(),questions:request.questions};
   while(true){
    const row=await channel('user_question',input,request.signal);
    if(row.state==='answered')return row.answer;
    await delay(2000,undefined,{signal:request.signal});
   }
  });
  ctx.on('agent/created',async({agent,signal})=>{
   if(!ctx.agentPresets.composedPreset(agent.ctx)){
    const persisted=ctx.sessionProjections.stateOf(agent.session,'agentPreset');
    if(persisted){
     if(persisted!==config.preset)throw new Error('Persisted Meta role identity mismatch');
     // Restoring a frozen composition is not a preset switch. select() rejects
     // any session with prior turns; mount() is the native resume binding API.
     await ctx.agentPresets.mount(agent.ctx,persisted);
    }else await ctx.agentPresets.select(agent,config.preset);
   }
   await channel('register',{agentId:agent.session.id,preset:ctx.agentPresets.composedPreset(agent.ctx),plugins:ctx.agentPresets.inspectCompositions(agent.ctx),tools:ctx.tools.schemas(agent).map(t=>t.name)},signal);
  });
 }
 actor(agent){return {agentId:agent.session.id};}
 runtime(action,input,signal){return channel(action,input,signal);}
 call(operation,input,exec){
  return channel('call',{...this.actor(exec.agent),operation,input:{...input,...(operation==='campaign_finish'?{reviewId:this.grants.get(exec.token)}:{})}},exec.signal);
 }
 observe(pluginId,event,exec){return channel('observe',{...this.actor(exec.agent),pluginId,event,callId:exec.callId},exec.signal);}
}
