// Shared frozen configuration; no SDK, credentials or provider dependencies.
export const OUTPUT_FAILURES=new Set(['invalid_tool_arguments','tool_argument_schema_error','stream_whitespace','tool_argument_size_limit','response_size_limit']);
export const STRATEGIES=['transient-recovery','response-recovery','tool-argument-recovery'];
export function recoveryPolicy(value){
 if(value==null)return null;
 const delays=value.retryDelaysSeconds;
 if(!['solver-request-recovery-v1','solver-request-recovery-v2'].includes(value.version)||!Array.isArray(delays)||
  delays.length!==5||delays.some(n=>!Number.isFinite(n)||n<=0||n>3600))throw new Error('Invalid Solver request recovery policy');
 if(value.version==='solver-request-recovery-v1')return Object.freeze({...value,retryDelaysSeconds:Object.freeze([...delays])});
 const content=value.contentRetryDelaysSeconds,strategies=value.strategies;
 if(!Array.isArray(content)||content.length>5||content.some(n=>!Number.isFinite(n)||n<0||n>60)||
  !Number.isInteger(value.maxChainRetries)||value.maxChainRetries<1||value.maxChainRetries>10||
  !Array.isArray(strategies)||new Set(strategies).size!==strategies.length||strategies.some(id=>!STRATEGIES.includes(id)))
  throw new Error('Invalid Solver request recovery policy');
 return Object.freeze({...value,retryDelaysSeconds:Object.freeze([...delays]),contentRetryDelaysSeconds:Object.freeze([...content]),strategies:Object.freeze([...strategies])});
}
export const hasStrategy=(policy,id)=>policy?.version==='solver-request-recovery-v2'&&policy.strategies.includes(id);
export function transientFailure(failure){
 if(failure?.status>=400&&failure.status<500)return false;
 return failure?.code==='TRANSPORT'||failure?.code==='SERVER'&&(failure.status===503||failure.message==='Model service overloaded');
}
