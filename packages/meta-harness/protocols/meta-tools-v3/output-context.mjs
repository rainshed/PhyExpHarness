import {channel} from './domain-control.mjs';
export const name='meta-output-context';
export const inject=['tools','systemPrompt'];
export function apply(ctx){
 ctx.systemPrompt.section({name:'phyexp:full-outputs',order:25,text:'Terminal previews may be shortened. Raw terminal bytes are captured before truncation and published under /outputs. Read /outputs/index.json to locate complete logs, including unfinished or interrupted commands. Use /work/analysis for scripts, /work/plugins for plugin drafts. Read /evidence/index.json for complete accessible material paths. Network is disabled; model requests are controlled by the host.'});
 ctx.on('tools/post-execute',async(exec,result,next)=>{
  const decision=await next();
  const receipt=await channel('tool_output',{agentId:exec.agent?.session.id,name:exec.name,callId:exec.callId,content:result.content,value:result.value,isError:result.isError});
  if(['evidence_list','sdk_read','results_compare','candidate_retain','campaign_status','candidate_list','report_save','report_get'].includes(exec.name)&&(result.value?.receiptVersion==='meta-tool-receipt-v1'||result.content?.some(c=>c.type==='text'&&c.text?.includes('\"receiptVersion\":\"meta-tool-receipt-v1\"'))))return decision;
  if(decision.kind!=='accept'||decision.value!==undefined)return decision;
  return {...decision,content:[...(decision.content||result.content),{type:'text',text:JSON.stringify({completeToolResult:receipt,terminalLogs:'/outputs/index.json'})}]};
 });
}
