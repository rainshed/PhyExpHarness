// The original backend published names; newer versions publish full model capabilities.
// Recognize that original contract explicitly instead of presenting its strings as missing draft entries.
const legacyModels=new Set(['gpt-6-sol','gpt-6-astra','gpt-6-luna']);
export function readModelCatalog(payload){
 if(!Array.isArray(payload?.models)||(!payload.models.length&&payload.schemaVersion!==2))throw Error('后台没有返回可用的模型目录，请重启后台后重试。');
 const legacy=payload.models.length>0&&payload.models.every(model=>typeof model==='string');
 const rows=legacy?payload.models.map(model=>{
  if(payload.provider!=='openai-codex'||!legacyModels.has(model))throw Error('后台模型目录格式不兼容，请更新并重启后台。');
  return {provider:payload.provider,model,name:model,reasoningEfforts:['low','medium','high','xhigh'],defaultReasoningEffort:'medium'};
 }):payload.models;
 const ids=new Set();
 for(const entry of rows){
  if(!entry||typeof entry.provider!=='string'||!entry.provider||typeof entry.model!=='string'||!entry.model||
     !Array.isArray(entry.reasoningEfforts)||entry.reasoningEfforts.some(e=>typeof e!=='string'||!e)||
     (entry.reasoningEfforts.length?!entry.reasoningEfforts.includes(entry.defaultReasoningEffort):entry.defaultReasoningEffort!=null)){
   throw Error('后台模型目录格式不兼容，请更新并重启后台。');
  }
  const id=entry.provider+'/'+entry.model;if(ids.has(id))throw Error('后台模型目录包含重复模型，请检查配置。');ids.add(id);
 }
 return {models:rows.map(entry=>({...entry,name:entry.name||entry.model})),
  note:legacy?'后台仍为旧版，目前仅提供 GPT 订阅模型；重启后台后可使用新的供应商目录。':''};
}
