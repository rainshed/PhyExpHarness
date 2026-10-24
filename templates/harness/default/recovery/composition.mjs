import Core from './core.mjs';
import * as transient from './transient.mjs';
import * as response from './response.mjs';
import * as toolArguments from './tool_arguments.mjs';
const plugins=new Map([transient,response,toolArguments].map(p=>[p.name,p]));
// Native Cordis lifecycle and service injection; declarative composition without a second loader.
export async function installRecoveryComposition(ctx,policy,deadline){
 await ctx.plugin(Core,{policy,deadline}).await();
 for(const id of policy.strategies)await ctx.plugin(plugins.get(id)).await();
 let service;
 await ctx.inject(['phyexpRecovery'],scoped=>{service=scoped.phyexpRecovery;}).await();
 if(!service||service.describe().strategies.length!==policy.strategies.length)throw new Error('Recovery composition did not load');
 return service;
}
