import {defineTool} from '@deepseek-ai/dsh-tools';
import Ajv from 'ajv';
import {nativeSchema} from './domain-tools.mjs';
import {channel} from './domain-control.mjs';
export const name='meta-child-output-adapter';
export const inject=['tools','systemPrompt'];
export function apply(ctx,config){
 const validate=new Ajv({strict:false}).compile(config.schema);
 const staged=new WeakMap();let captured=false;
 ctx.tools.register(defineTool({name:'structured_output',description:'Submit your final structured result exactly once.',parameters:nativeSchema(config.schema).properties,
  output:{schema:{type:'object',additionalProperties:true},render:()=>[{type:'text',text:'Structured output recorded.'}]},
  async execute(args,exec){if(captured||!validate(args))throw new Error('Invalid or duplicate structured output');staged.set(exec,args);exec.concludeTurn();return {recorded:true};}}));
 ctx.on('tools/result',async(exec,result)=>{
  if(exec.name==='structured_output'&&!result.isError&&staged.has(exec)){captured=true;await channel('child_output',{result:staged.get(exec)});staged.delete(exec);}
 });
 ctx.systemPrompt.section({name:'phyexp:structured-output',order:100,text:'When your research is complete, call structured_output. A plain text answer does not submit a structured result.'});
}
