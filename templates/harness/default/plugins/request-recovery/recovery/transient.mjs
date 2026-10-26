import {transientFailure} from './policy.mjs';
export const name='transient-recovery';
export const inject=['phyexpRecovery'];
export function apply(ctx){
 ctx.effect(()=>ctx.phyexpRecovery.register({id:name,category:'transport',action:'retry',
  matches:(failure,mode)=>mode==='request'&&transientFailure(failure)}));
}
