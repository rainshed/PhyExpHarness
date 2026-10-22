import {registerDomain} from './domain-tools.mjs';
export const name='meta-campaign';
export const inject=['tools','systemPrompt','metaControl'];
export function apply(ctx,config){
 ctx.systemPrompt.section({name:'phyexp:campaign',order:20,text:config.text,complete:false,interpolate:false});
 registerDomain(ctx,config,'campaign');
}
