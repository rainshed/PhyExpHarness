export const name='meta-literal-context';
export const inject=['systemPrompt'];
export function apply(ctx,config){
 if(!config.text?.trim())throw new Error('Frozen literal context required');
 ctx.effect(()=>ctx.systemPrompt.section({name:'phyexp:activity-context',order:10,text:config.text,interpolate:false}));
}
