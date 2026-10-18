import { defineTool } from '@deepseek-ai/dsh-tools';
import { apply as nativeInspect } from '@deepseek-ai/dsh-tool-cordis';
export const name='phyexp-meta-harness';
export const inject=['tools','systemPrompt'];
export const operations={
 materials_list:'List allowed materials in this Campaign. Input: {kind?,task?,candidateId?,batchId?,offset?,limit?}. Kinds: activity, task, sdk, version, plugin, experiment, evidence, analysis, guide. Returns stable refs, provenance and availability; no host paths.',
 materials_search:'Search allowed material text, including trajectories and past analyses. Input: {query,kind?,task?,candidateId?,batchId?,offset?,limit?}. Returns matching refs and character offsets. Analysis is not official evidence.',
 materials_read:'Read a material ref returned by materials_list/search. Input: {ref,offset?,limit?}. Character offsets; default 16000, max 32000. Includes provenance and digest. Entry refs: activity:current, guide:interface, guide:reporting.',
 sdk_search:'Search version-matched execution plugin documentation. Input: {query}.',
 sdk_read:'Read an indexed SDK document. Input: {id,offset?,limit?}.',
 sdk_inspect:'Inspect a public execution API declaration. Input: {name}. No method execution.',
 workspace_read:'Read plugin source. Input: {path,candidateId?}. With candidateId, path is relative to that frozen candidate’s plugins directory.',
 workspace_write:'Write a plugin workspace file. Input: {path,content}.',
 workspace_exec:'Run a development check in the isolated workspace. Input: {command}.',
 candidate_freeze:'Check and freeze an execution plugin combination. Input: {plugins:[{path,config}],parent?,description,displayName?,idempotencyKey}. Each path is a plugin DIRECTORY containing plugin.json, not the manifest file path.',
 candidate_list:'List frozen candidates. Input: {}.',
 batch_submit:'Submit one candidate, task list and repeat count. Input: {candidateId,tasks,repeats,idempotencyKey}.',
 campaign_status:'Read current objective, fixed models, budgets and state. Input: {view?:"summary"|"full"}. Default summary; detailed materials are queryable separately.',
 evidence_read:'Read an allowed evidence item. Input: {id,offset?,limit?}.',
 evidence_list:'List allowed evidence and official results. Input: {batchId?}.',
 report_save:'Save evidence-based analysis. Input: {batchId?,summary,process,problems,pluginContributions:[{plugin,expected,observed,comparison,assessment,evidenceRefs}],observations,hypotheses,limitations,decision,evidenceRefs}. Omit batchId for final report.',
 candidate_retain:'Select a candidate with supporting evidence. Input: {candidateId,reason,evidenceRefs}.',
 campaign_finish:'End exploration and request closeout. Input: {reason}. Explain the applicable stop condition, evidence, unresolved issues and remaining resources; an explanation is not platform verification of stability.',
 export_create:'Export an existing frozen candidate. Input: {candidateId}. Does not run experiments.',
};
export function apply(ctx,config={}){
 if(typeof config.systemPrompt!=='string'||!config.systemPrompt.trim())throw new Error('Meta system prompt must be supplied by the controller');
 ctx.systemPrompt.section({name:'phyexp:meta-system',order:0,text:config.systemPrompt,complete:true,interpolate:false});
 // The native tools see only a target-SDK provider, never the control/UI host registry.
 nativeInspect({tools:ctx.tools,cordisInspect:{
  list:()=>[{platform:'host',id:'execution-sdk',purpose:'Version-matched execution SDK declarations',
    methods:['search','read','inspect'].map(name=>({name,inputSchema:{type:'object'},outputSchema:{type:'object'}}))}],
  async query(platform,provider,method,input,_agent,signal){
   if(platform!=='host'||provider!=='execution-sdk'||!['search','read','inspect'].includes(method))throw new Error('Inspect provider unavailable');
   return call('sdk_'+method,input,signal);
  },
 }});
 for(const [name,description] of Object.entries(operations)) ctx.tools.register(defineTool({name,description,
  parameters:{input:{type:'string',required:true,description:'JSON object matching the documented operation input.'}},
  output:{schema:{type:'string'},render:(_args,value)=>[{type:'text',text:value}]},
  async execute({input},exec){
   return JSON.stringify(await call(name,JSON.parse(input),exec.signal));
  }}));
}
async function call(operation,input,signal){
 const response=await fetch(process.env.PHYEXP_GATEWAY_URL+'/meta',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({operation,input}),signal});
 if(!response.ok)throw new Error(`Meta interface refused: ${response.status}`);
 const rows=(await response.text()).trim().split('\n').filter(Boolean).map(JSON.parse);
 const failure=rows.find(r=>r.error);if(failure)throw new Error(failure.error);
 return rows.map(r=>r.result).at(-1);
}
