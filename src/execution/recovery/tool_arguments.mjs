import {validateJsonSchemaValue} from '@deepseek-ai/dsh-tools';
export const name='tool-argument-recovery';
export const inject=['phyexpRecovery','tools'];
export function apply(ctx){
 ctx.effect(()=>ctx.phyexpRecovery.register({id:name,category:'content',action:'tool-feedback',
  matches:(failure,mode)=>mode==='feedback'&&failure?.code==='MODEL_OUTPUT_INVALID'}));
 // A monotonic native guard cannot be bypassed by a pre-execute allow decision.
 ctx.tools.guard(exec=>{
  const issue=exec.agent&&ctx.phyexpRecovery.state(exec.agent.session,'step')?.issues?.find(i=>i.callId===exec.callId);
  if(issue)return issue.message;
  const schema=ctx.tools.get(exec.name,exec.agent)?.parameters;
  if(schema&&validateJsonSchemaValue(schema,exec.arguments).length)
   return 'Invalid tool arguments: provide an object matching the declared tool schema. The tool was not executed.';
 });
}
