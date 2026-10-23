import {defineTool} from '@deepseek-ai/dsh-tools';
import Ajv from 'ajv';
import contract from './contracts.json' with {type:'json'};
import analysis from './report-analysis.schema.json' with {type:'json'};
import receiptSchema from './receipt.schema.json' with {type:'json'};
import research from './research.schema.json' with {type:'json'};
contract.operations.research_save.input.properties.record=research;
contract.operations.report_save.input.properties.analysis=analysis;

export const operations=contract.operations;
const ajv=new Ajv({allErrors:true});
const validators=new Map();
const validateReceipt=ajv.compile(receiptSchema);
export function validateInput(name,input){
 const spec=operations[name];if(!spec)throw new Error('Unknown Meta operation');
 if(!validators.has(name))validators.set(name,ajv.compile(spec.input));
 const validate=validators.get(name);
 if(!validate(input))throw new Error(`Invalid ${name} input: ${ajv.errorsText(validate.errors)}`);
 return input;
}
// Native schema annotations express requiredness per property, including nested objects.
export function nativeSchema(schema){
 const {required,$id,examples,minLength,maxLength,minItems,maxItems,minimum,maximum,const:constant,pattern,uniqueItems,...result}=schema;
 // The native DSL lacks these validation keywords; retain them in descriptions
 // and enforce the authoritative schema in JS and Python.
 if(constant!==undefined)result.enum=[constant];
 const constraints=[...Object.entries({maxLength,minItems,maxItems,minimum,maximum}).filter(([,v])=>v!==undefined).map(([k,v])=>`${k}: ${v}.`),minLength!==undefined?`Minimum length: ${minLength}.`:null,pattern?`Must match ${pattern}.`:null,uniqueItems?'Items must be unique.':null].filter(Boolean);
 if(constraints.length)result.description=[result.description,...constraints].filter(Boolean).join(' ');
 if(schema.properties)result.properties=Object.fromEntries(Object.entries(schema.properties).map(([key,value])=>[key,{...nativeSchema(value),...(required?.includes(key)?{required:true}:{})}]));
 if(schema.items)result.items=nativeSchema(schema.items);
 return result;
}
export function registerDomain(ctx,config,domain){
 for(const [name,spec] of Object.entries(operations).filter(([,v])=>v.plugin===domain&&(!config.observeOnly||!v.write))){
  ctx.tools.register(defineTool({name,
   description:spec.description||name,
   parameters:nativeSchema(spec.input).properties,
   output:{schema:{type:'object',additionalProperties:true},render:(_args,result)=>renderResult(result)},
   async execute(input,exec){
    try{validateInput(name,input);}catch(error){if(name!=='report_save')return {ok:false,error:{code:'invalid_input',message:error.message,retryable:false}};}
    await ctx.metaControl.observe(config.pluginId,'triggered',exec);
    return ctx.metaControl.call(name,input,exec);
   }}));
 }
}

export function renderResult(result){
 const text=JSON.stringify(result);
 if(result?.receiptVersion===receiptSchema.properties.receiptVersion.const){
  if(!validateReceipt(result))throw new Error('Invalid Meta receipt shape');
  if(Buffer.byteLength(text,'utf8')>4096)throw new Error('Meta receipt exceeds its contract');
 }
 return [{type:'text',text}];
}
