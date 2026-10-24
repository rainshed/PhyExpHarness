import React,{useState} from 'react';
import {api,key,duration} from './common';
import {NumberField} from './fields';
const allLabels:any={parallelism:'实际并发',defaultTrialTimeSeconds:'后续单次时长（秒）',closeoutReserveSeconds:'计划收尾预留（秒）'};
export function ResourcePlan({c}:any){
 const value=c.resourcePlanning;
 const [editing,setEditing]=useState(false),[draft,setDraft]=useState<any>({}),[revision,setRevision]=useState(0),[reason,setReason]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 if(value?.policy!=='meta-resource-planning-v1')return null;
 const plan=value.plan,benchmark=value.executionTimePolicy?.version==='benchmark-time-v1';
 const labels=Object.fromEntries(Object.entries(allLabels).filter(([key])=>key!=='defaultTrialTimeSeconds'||!benchmark));
 async function save(){
  const changes=Object.fromEntries(Object.keys(labels).map(k=>[k,Number(draft[k])]));
  if(c.config.modelAccessPolicy!=='control-only-v1')changes.closeoutReserveTokens=draft.closeoutReserveTokens??0;
  if(!reason.trim()||Object.entries(changes).some(([k,v])=>!Number.isSafeInteger(v)||v<(k.startsWith('closeout')?0:1))){setMessage('请填写有效整数和调整理由。');return;}
  setBusy(true);setMessage('');
  try{await api('/campaigns/'+c.id+'/plan',{changes,reason,expectedPlanRevision:revision,idempotencyKey:key()});setEditing(false);setMessage('计划已保存；未来批次采用新计划，已受理和运行任务保持原条件。')}
  catch(e:any){setMessage(e.message)}finally{setBusy(false)}
 }
 return <section className="mh-card"><h3>资源计划与实际条件</h3>
  {plan?<p>计划版本 {plan.revision} · 来源 {plan.source} · 计划并发 {plan.parallelism} · 有效并发 {value.effectiveParallelism} · {benchmark?'单题时限遵循 benchmark':'后续单次 '+duration(plan.defaultTrialTimeSeconds)}<br/>计划收尾：{duration(plan.closeoutReserveSeconds)}。理由：{plan.reason}</p>:<p>等待 Meta 提交初始计划，计划就绪后启动基线。</p>}
  <p>用户上限与计划分别执行。提高活动上限不会同步延长已启动进程；已受理批次保留其条件快照。</p>
  {benchmark?<p>每题求解与评分分别按 benchmark 时限执行。活动剩余时间不足时不启动该题。</p>:value.executionTimePolicy&&<p>单次时长包含启动、Solver、官方评分和清理；其中固定预留 {value.executionTimePolicy.trialCloseoutReserveSeconds} 秒用于评分与清理，启动还会消耗部分时间。这与 Meta 的活动收尾预留分别记录。</p>}
  {value.schedulingWait&&<p role="status">待执行任务正在等待{value.schedulingWait.reason==='closeout_time'?'收尾时间预留调整':'历史运行限制解除'}；已通知 Meta 检查计划和总体上限。</p>}
  <details><summary>配置来源与运行任务条件</summary><ul>{Object.entries(value.configurationSources||{}).filter(([key])=>!['softTokenLimit','reserveTokens'].includes(key)).map(([k,v]:any)=><li key={k}>{k}：{c.config[k]??'未设置'} · {v.source}</li>)}</ul>
   {(value.runningConditions||[]).map((t:any)=><p key={t.id}>{t.task}：{benchmark?'求解上限 '+duration(t.effectiveConditions?.solverTimeSeconds):'实际获配 '+duration(t.effectiveConditions?.actualTimeSeconds)}；活动截止 {new Date(t.deadline*1000).toLocaleString()}。</p>)}
  </details>
  {['draft','running','paused'].includes(c.state)&&(!c.explorationClosed||c.counts.activeTrials>0||c.counts.reservedTrials>0)&&!editing&&<button onClick={()=>{setDraft(plan||value.suggestions);setRevision(value.planRevision);setReason('');setMessage('');setEditing(true)}}>调整运行计划</button>}
  {editing&&<div><div className="mh-grid">{Object.entries(labels).map(([k,label])=><NumberField key={k} label={label} value={draft[k]} onChange={(v:any)=>setDraft({...draft,[k]:v})}/>)}</div><label>调整理由<input value={reason} onChange={e=>setReason(e.target.value)}/></label><button disabled={busy} onClick={save}>保存计划</button><button disabled={busy} onClick={()=>setEditing(false)}>取消</button></div>}
  {message&&<p role="status">{message}</p>}
 </section>;
}
