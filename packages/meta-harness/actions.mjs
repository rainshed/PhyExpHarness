import {defineTool} from '@deepseek-ai/dsh-tools';
import {operations} from './legacy.mjs';
import {readOperations} from './queries.mjs';
export const name='meta-actions';
export const inject=['tools','metaControl'];
export function apply(ctx,config){
 for(const name of Object.keys(operations).filter(n=>!readOperations.includes(n)))ctx.tools.register(defineTool({name,
  description:name==='campaign_finish'?'Request closeout. Input: {condition:"exhausted"|"stable",candidateId,reason,evidenceRefs:[string],attempts:[{direction,evidenceRefs:[string],finding}],remainingDirections:[string],unresolved:[string]}. Exhausted invokes an independent read-only reviewer. Explain genuinely different attempts and why remaining feasible directions are unpromising. Denial means continue. Stable requires a user-agreed machine-checkable stabilityRule. Do not retry identical requests.':operations[name],
  parameters:{input:{type:'string',required:true}},output:{schema:{type:'string'},render:(_a,v)=>[{type:'text',text:v}]},
  async execute({input},exec){await ctx.metaControl.observe(config.pluginId,'triggered',exec);return JSON.stringify(await ctx.metaControl.call(name,JSON.parse(input),exec));}}));
}
