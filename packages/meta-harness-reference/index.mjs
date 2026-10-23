import {defineTool} from '@deepseek-ai/dsh-tools';
import Ajv from 'ajv';
import contract from './contracts.json' with {type:'json'};
export const name = "meta-harness-reference";
export const inject = ['tools', 'metaControl'];
export const operations = contract.operations;
const ajv = new Ajv({allErrors:true});
const validators = Object.fromEntries(Object.entries(operations).map(([id,spec])=>[id,ajv.compile(spec.input)]));
// Native DSL annotations are only presentation; the full JSON schema is authoritative.
function native(schema) {
  const {required,minimum,maximum,minLength,maxLength,minItems,maxItems,uniqueItems,...result}=schema;
  if(schema.properties) result.properties=Object.fromEntries(Object.entries(schema.properties).map(([key,value])=>[key,{...native(value),...(required?.includes(key)?{required:true}:{})}]));
  if(schema.items) result.items=native(schema.items);
  return result;
}
export function apply(ctx, config={}) {
  if(config.observeOnly) return;
  for(const [id,spec] of Object.entries(operations)) ctx.tools.register(defineTool({
    name:id, description:spec.description, parameters:native(spec.input).properties,
    output:{schema:{type:'object',additionalProperties:true},render:(_args,result)=>[{type:'text',text:JSON.stringify(result)}]},
    async execute(input,exec) {
      if(!validators[id](input)) return {ok:false,error:{code:'invalid_input',message:ajv.errorsText(validators[id].errors),retryable:false}};
      await ctx.metaControl.observe(name,'triggered',exec);
      return ctx.metaControl.call(id,input,exec);
    },
  }));
}
