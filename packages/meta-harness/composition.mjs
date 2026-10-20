import path from 'node:path';
export function validateComposition(manifest){
 if(manifest.version!=='meta-composition-v1'||!Array.isArray(manifest.plugins))throw new Error('Unsupported Meta composition');
 const ids=new Set();const native=new Set(['systemPrompt','tools','subagents']);
 for(const row of manifest.plugins){
  if(!row.id||ids.has(row.id)||!['host','meta','reviewer'].includes(row.scope)||!/^[-\w]+\.mjs$/.test(row.module))throw new Error('Invalid or duplicate Meta plugin');
  ids.add(row.id);
 }
 const enabled=manifest.plugins.filter(p=>p.enabled);
 for(const row of enabled)for(const need of row.requires||[]){
  if(!native.has(need)&&!enabled.some(p=>(p.id===need||(p.provides||[]).includes(need))&&(p.scope==='host'||p.scope===row.scope)))throw new Error(`${row.id}: missing dependency ${need}`);
 }
 if(!enabled.some(p=>p.scope==='host'&&(p.provides||[]).includes('metaControl')))throw new Error('Meta control service required');
 return manifest;
}
export function compositionEntries(manifest,{root='/opt/phyexp/meta-plugin',systemPrompt,reviewerPrompt,compositionId}={}){
 validateComposition(manifest);
 const rows=scope=>manifest.plugins.filter(p=>p.enabled&&p.scope===scope).map(p=>({id:p.id,name:path.posix.join(root,p.module),config:{...p.config,pluginId:p.id,compositionId,...(scope!=='host'?{text:scope==='meta'?systemPrompt:reviewerPrompt}:{})}}));
 const preset=(id,scope,prefix)=>({id,name:'@deepseek-ai/dsh-agent-preset',config:{id,name:id,plugins:[
  {id:'persona',name:'@deepseek-ai/dsh-persona',config:{prefix,complete:false,includeRuntimeContext:false}},...rows(scope)]}});
 return [
  {id:'meta-presets',name:'@deepseek-ai/dsh-agent-preset-registry',config:{default:'phyexp-meta'}},
  {id:'meta-subagents',name:'@deepseek-ai/dsh-subagent',config:{maxActiveSubagents:1}},
  {id:'meta-spawn',name:'@deepseek-ai/dsh-subagent-spawn-in-process'},
  ...rows('host'),preset('phyexp-meta','meta','你是执行 Harness 的设计与改进者。'),
  preset('phyexp-stop-reviewer','reviewer','你是独立的提前停止审查员。')
 ];
}
