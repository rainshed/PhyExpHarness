import React from 'react';

export function ModelFields({role,label,note,model,catalog,onChange}:any){
 const value=model.provider+'/'+model.model;
 const selected=catalog.find((m:any)=>m.provider+'/'+m.model===value);
 const providers=[...new Set(catalog.map((m:any)=>m.provider))];
 return <fieldset><legend>{label}</legend>
  <select aria-label={label} value={value} onChange={e=>{
   const entry=catalog.find((m:any)=>m.provider+'/'+m.model===e.target.value);
   if(entry)onChange({provider:entry.provider,model:entry.model,...(entry.defaultReasoningEffort?{reasoningEffort:entry.defaultReasoningEffort}:{})});
  }}>
   {!selected&&<option disabled value={value}>{catalog.length?'草稿模型未配置，请重新选择':'尚无可选模型，请管理供应商与模型'}</option>}
   {providers.map((provider:any)=><optgroup key={provider} label={catalog.find((m:any)=>m.provider===provider)?.providerName||provider}>{catalog.filter((m:any)=>m.provider===provider).map((m:any)=><option key={m.model} value={m.provider+'/'+m.model}>{m.name}</option>)}</optgroup>)}
  </select>
  {!!selected?.reasoningEfforts.length?<label>推理强度<select aria-label={label+'推理强度'} value={model.reasoningEffort} onChange={e=>onChange({...model,reasoningEffort:e.target.value})}>
   {selected.reasoningEfforts.map((effort:string)=><option key={effort}>{effort}</option>)}
  </select></label>:selected&&<small>此模型无需设置推理强度。</small>}
  {!selected&&!!catalog.length&&<small role="alert">{label}的草稿模型已不在当前目录中，请重新选择。</small>}
  <small>{note}</small>
 </fieldset>;
}
