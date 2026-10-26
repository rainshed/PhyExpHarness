import {OUTPUT_FAILURES} from './policy.mjs';
export const name='response-recovery';
export const inject=['phyexpRecovery'];
export function apply(ctx){
 ctx.effect(()=>ctx.phyexpRecovery.register({id:name,category:'content',action:'retry',
  matches:(failure,mode)=>mode==='request'&&failure?.code==='MODEL_OUTPUT_INVALID'&&OUTPUT_FAILURES.has(failure.outputCode)}));
}
