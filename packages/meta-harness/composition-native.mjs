import path from 'node:path';
export const presets={meta:'phyexp-meta',research:'phyexp-researcher',reviewer:'phyexp-stop-reviewer'};
export function validateNativeComposition(manifest){
 if(manifest.version!=='meta-composition-v2'||!Array.isArray(manifest.plugins))throw new Error('Invalid native Meta composition');
 const ids=new Set();const native=['tools','systemPrompt','subagents'];
 for(const p of manifest.plugins){
  if(!p.id||ids.has(p.id)||!/^[-\w]+\.mjs$/.test(p.module)||!Array.isArray(p.roles)||p.roles.some(r=>!presets[r])||typeof p.enabled!=='boolean')throw new Error('Invalid/duplicate Meta plugin');
  ids.add(p.id);
 }
 const enabled=manifest.plugins.filter(p=>p.enabled);
 for(const role of Object.keys(presets))if(!enabled.some(p=>p.roles.includes(role)&&(p.provides||[]).includes('metaControl')))throw new Error('Missing scoped metaControl');
 for(const p of enabled)for(const role of p.roles)for(const need of p.requires||[]){
  if(!native.includes(need)&&!enabled.some(q=>q.roles.includes(role)&&(q.id===need||(q.provides||[]).includes(need))))throw new Error('Missing dependency '+need);
 }
 if(manifest.mode==='complete')for(const id of ['meta-control','meta-campaign','meta-experiments','meta-evidence','meta-reporting'])if(!enabled.some(p=>p.id===id&&p.roles.includes('meta')))throw new Error('Missing complete Meta capability '+id);
 return manifest;
}
export function nativeEntries(manifest,{root='/opt/phyexp/meta-plugin',role='meta',systemPrompt,reviewerPrompt,compositionId,outputSchema}={}){
 validateNativeComposition(manifest);if(!presets[role])throw new Error('Unknown Meta role');
 const entry=(id,name,config)=>({id,name,config});
 const native=(id,config)=>entry('native-'+id,'@deepseek-ai/dsh-'+id,config);
 const local=(id,module,config)=>entry(id,path.posix.join(root,module),config);
 const domain=manifest.plugins.filter(p=>p.enabled&&p.roles.includes(role));
 const rolePlugins=scopedRole=>{
  const text=scopedRole==='meta'?systemPrompt:scopedRole==='reviewer'?reviewerPrompt:'You are an independent research assistant in the activity research environment. Follow the delegated task and inspect the shared authorized files. Your native working directory is effective; use a separate directory or copy when concurrent edits require it. Send concise findings and file paths to your parent with send_message. Only the main Meta submits business changes. Research has no separate five-minute lifetime; the activity deadline and budget still apply.';
  const plugins=manifest.plugins.filter(p=>p.enabled&&p.roles.includes(scopedRole)&&!p.provides?.includes('metaControl')).map(p=>local(p.id,p.module,{...p.config,pluginId:p.id,compositionId,observeOnly:scopedRole!=='meta',text}));
  plugins.unshift(native('persona',{prefix:'You are a helpful research and software engineering assistant.',complete:false,includeRuntimeContext:true}));
  if(scopedRole==='meta')plugins.push(native('tool-subagent',{provider:'spawn',agentPreset:presets.research,modelSelectionSettings:false,maxDepth:1}),native('tool-ask-user',{}));
  if(scopedRole!=='reviewer')plugins.push(native('tool-subagent-control',{}));
  if(scopedRole==='meta')plugins.push(entry('native-list-agents','@deepseek-ai/dsh-tool-subagent-control/list-agents',{}));
  if(outputSchema&&scopedRole===role)plugins.push(local('child-output','child-output.mjs',{schema:outputSchema}));
  return plugins;
 };
 return [native('agent-preset-registry',{default:presets[role]}),
  ...(role==='meta'?[native('subagent',{maxActiveSubagents:2}),native('subagent-spawn-in-process',{}),local('meta-isolated-backend','isolated-subagent.mjs'),native('user-questions',{})]:[]),
  ...domain.filter(p=>p.provides?.includes('metaControl')).map(p=>local(p.id,p.module,{...p.config,preset:presets[role]})),
  native('tool-fs-search',{sampleOverCapGlobResults:false}),native('tool-terminal',{}),native('tool-jobs',{}),
  native('tool-todo',{allowParallelInProgress:true}),native('skill',{}),native('skill-filesystem',{includeDefaultRoots:true,customSkillDirs:['/sdk/skills'],watch:false}),native('tool-skill',{}),
  native('session-query',{}),native('tool-session-query',{}),native('spill-local',{root:'/session/spills',cleanupPeriodDays:0}),
  local('complete-output-context','output-context.mjs'),
  ...(role==='meta'?[entry('research-declaration','@deepseek-ai/dsh-agent-preset',{id:presets.research,name:'Native research assistant',plugins:rolePlugins('research')}),entry('review-declaration','@deepseek-ai/dsh-agent-preset',{id:presets.reviewer,name:'Isolated stop reviewer',plugins:[]})]:[]),
  entry('active-meta-preset','@deepseek-ai/dsh-agent-preset',{id:presets[role],name:presets[role],plugins:rolePlugins(role)})];
}
