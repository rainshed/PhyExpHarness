import {defineTool} from '@deepseek-ai/dsh-tools';
import {apply as nativeInspect} from '@deepseek-ai/dsh-tool-cordis';
import {operations} from './legacy.mjs';
export const name='meta-queries';
export const inject=['tools','metaControl'];
export const readOperations=['materials_list','materials_search','materials_read','sdk_search','sdk_read','sdk_inspect','workspace_read','candidate_list','campaign_status','evidence_read','evidence_list'];
export function apply(ctx,config){
 for(const name of readOperations)ctx.tools.register(defineTool({name,description:operations[name],
  parameters:{input:{type:'string',required:true}},output:{schema:{type:'string'},render:(_a,v)=>[{type:'text',text:v}]},
  async execute({input},exec){await ctx.metaControl.observe(config.pluginId,'triggered',exec);return JSON.stringify(await ctx.metaControl.call(name,JSON.parse(input),exec));}}));
 nativeInspect({tools:ctx.tools,cordisInspect:{
  list:()=>[{platform:'host',id:'execution-sdk',purpose:'Version-matched execution SDK declarations',methods:['search','read','inspect'].map(name=>({name,inputSchema:{type:'object'},outputSchema:{type:'object'}}))}],
  async query(platform,provider,method,input,agent,signal){
   if(platform!=='host'||provider!=='execution-sdk'||!['search','read','inspect'].includes(method))throw new Error('Inspect provider unavailable');
   return ctx.metaControl.call('sdk_'+method,input,{agent,signal});
  }
 }});
}
