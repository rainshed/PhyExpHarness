import {Service} from '@deepseek-ai/cordis';
import {createHmac,randomUUID} from 'node:crypto';
// This service lives only in the trusted Meta Runner, never in generated-code check Runners.
export default class MetaControl extends Service{
 static inject=['agentPresets','tools'];
 constructor(ctx,config){
  super(ctx,'metaControl');this.config=config;this.grants=new WeakMap();
  ctx.on('agent/created',async ({agent,signal})=>{
   if(!ctx.agentPresets.composedPreset(agent.ctx))await ctx.agentPresets.select(agent,'phyexp-meta');
   const preset=ctx.agentPresets.composedPreset(agent.ctx);
   await this.runtime('register',{agentId:agent.session.id,preset,plugins:ctx.agentPresets.inspectCompositions(agent.ctx),tools:ctx.tools.schemas(agent).map(t=>t.name)},signal);
  });
 }
 async runtime(action,input,signal){
  const message=JSON.stringify({nonce:randomUUID(),action,input});
  const signature=createHmac('sha256',process.env.PHYEXP_META_BRIDGE_KEY).update(message).digest('hex');
  const response=await fetch(process.env.PHYEXP_GATEWAY_URL+'/meta',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({message,signature}),signal});
  if(!response.ok)throw new Error(`Meta interface refused: ${response.status}`);
  const rows=(await response.text()).trim().split('\n').filter(Boolean).map(JSON.parse);
  const error=rows.find(r=>r.error);if(error)throw new Error(error.error);
  return rows.map(r=>r.result).at(-1);
 }
 actor(agent){if(!agent)throw new Error('Agent required');return {agentId:agent.session.id};}
 call(operation,input,exec){
  if(operation==='campaign_finish')input={...input,reviewId:this.grants.get(exec.token)};
  return this.runtime('call',{...this.actor(exec.agent),operation,input},exec.signal);
 }
 observe(pluginId,event,exec){return this.runtime('observe',{...this.actor(exec.agent),pluginId,event,callId:exec.callId},exec.signal);}
}
