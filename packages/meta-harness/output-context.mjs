import {randomUUID} from 'node:crypto';
import {defineTool} from '@deepseek-ai/dsh-tools';
import {channel} from './domain-control.mjs';
export const name='meta-output-context';
export const inject=['tools','systemPrompt'];
const PAGES=new Set(['tool_result_read','evidence_read','materials_read','read','grep','glob','ls','bash','session_event_read','session_search','session_search_all','session_list','session_events']);
const bytes=value=>Buffer.byteLength(JSON.stringify(value),'utf8');
export async function archiveOutput(value,send=channel){
 const id=randomUUID();
 await send('output_open',{id,kind:value.value?.receiptVersion==='meta-tool-receipt-v1'?'business-receipt':'tool-result'});
 const data=Buffer.from(JSON.stringify(value));let sequence=0;
 for(let i=0;i<data.length;i+=64*1024)await send('output_append',{id,sequence:sequence++,bytes:data.subarray(i,i+64*1024).toString('base64')});
 return send('output_close',{id});
}
export function projectOutput(exec,result,decision,file){
 const content=decision.kind==='block'?decision.feedback:decision.content??result.content;
 const isError=result.isError||decision.kind==='block';
 const budget=PAGES.has(exec.name)&&!isError?64*1024:4096;
 const contexts=[...(decision.additionalContexts||[]),...(result.additionalContexts||[])];
 const changed=decision.value!==undefined||contexts.length;
 if(!isError&&!changed&&bytes(content)<=budget&&bytes(result.value??null)<=budget)return decision;
 const receipt={status:isError?'failed':'completed',summary:isError?'工具未成功；完整诊断见文件。':'完整结果见文件；使用 tool_result_read 分页读取。',file};
 const compact=[{type:'text',text:JSON.stringify(receipt)}];
 // Blocking is the SDK's only way to discard deferred contexts. Preserve the
 // actual execution outcome in the receipt; a delivery block is not a rollback.
 return isError||contexts.length?{kind:'block',feedback:compact}:{kind:'accept',content:compact};
}
export function apply(ctx){
 ctx.systemPrompt.section({name:'phyexp:full-outputs',order:25,text:'Complete tool results and raw terminal bytes are stored under /outputs; business evidence is under /materials and /evidence. Receipts are bounded. Use tool_result_read(path, offset, limit, sha256) for Unicode-character pages, including large session_event_read results, errors and review findings; use returned nextOffset and sha256. /outputs/index.json lists interrupted logs and completeness. Use /work/analysis for scripts and /work/plugins for drafts. Network is disabled; model requests are controlled by the host.'});
 ctx.tools.register(defineTool({name:'tool_result_read',description:'Read an authorized evidence/result file by Unicode-character pages (limit <=8192). Use the returned nextOffset and SHA-256 for subsequent pages.',
  parameters:{path:{type:'string',required:true},offset:{type:'integer'},limit:{type:'integer'},sha256:{type:'string'}},
  output:{schema:{type:'object',additionalProperties:true},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},
  execute:(input,exec)=>channel('file_read',input,exec.signal)}));
 ctx.on('tools/post-execute',async(exec,result,next)=>{
  const decision=await next();
  const file=await archiveOutput({agentId:exec.agent?.session.id,name:exec.name,callId:exec.callId,content:result.content,value:result.value,isError:result.isError,error:result.error,additionalContexts:result.additionalContexts,decision});
  return projectOutput(exec,result,decision,file);
 });
}
