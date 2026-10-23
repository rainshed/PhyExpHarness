import React,{useEffect,useRef,useState} from 'react';
import {defaultReferencePolicy,toggleReference,referenceError,readReferenceCatalog,saveReferencePolicy,cancelReferenceBatch} from '@phyexp/meta-workbench-client/reference';
import {api} from '@phyexp/meta-workbench-client';
import {states,tasks,number} from './common';
const modes:any={'model-reference':'参考模型 × 执行候选','harness-reference':'固定 Solver × 参考 Harness','joint-reference':'参考模型 × 参考 Harness'};
const compatibilityLabels:any={supported:'可组合',unsupported:'不兼容',unverified:'尚未验证','temporarily-unavailable':'暂不可用'};
export function ReferenceFields({value,onChange,frozen,catalog:provided,disabled=false}:any){
 const policy=value||defaultReferencePolicy();const current=useRef(policy);current.current=policy;
 const [catalog,setCatalog]=useState<any>(provided||null),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 useEffect(()=>{if(provided)setCatalog(provided)},[provided]);
 async function load(){setLoading(true);setError('');try{const next=await readReferenceCatalog();setCatalog(next);onChange({...current.current,catalogRevision:next.revision});}catch(e:any){setError(e.message)}finally{setLoading(false)}}
 useEffect(()=>{if(policy.modelEnabled&&!frozen&&!catalog)void load()},[policy.modelEnabled]);
 const models=catalog?.models||[],harnesses=catalog?.harnesses||[{id:'codex',name:'Codex'},{id:'claude-code',name:'Claude Code'},{id:'dsh-standard',name:'DeepSeek Harness 标准模式'}];
 const change=(values:any)=>onChange({...policy,...values});
 return <fieldset disabled={disabled} className="studio-reference-settings"><legend>参考实验插件</legend>
  <p>Meta 可按研究需要选择单个组合、任务与重复次数。每次参考实验共享活动的时间、次数、并发和用量额度。</p>
  <div className="mh-grid">{[['model','参考模型插件','选定参考模型运行已检查的执行候选。'],['harness','参考 Harness 插件','固定 Solver 运行选定 Harness；两个插件均开启时，也允许参考模型与参考 Harness 组合。']].map(([axis,label,note])=><fieldset key={axis}>
   <legend>{label}</legend><label className="mh-check"><input type="checkbox" checked={policy[axis+'Enabled']} disabled={!!frozen&&!frozen[axis+'Enabled']||catalog?.plugins?.[axis]===false} onChange={e=>change({[axis+'Enabled']:e.target.checked})}/>启用{label}</label><small>{note}</small>
   {catalog?.plugins?.[axis]===false&&<p>此插件包未安装。</p>}
   {axis==='model'&&policy.modelEnabled&&<><p>模型来源：DeepSeek Harness 原生 Models 配置。模型参数与供应商设置随活动冻结。</p>{!frozen&&<button type="button" disabled={loading} onClick={load}>{loading?'正在读取…':'读取 / 刷新原生模型'}</button>}{models.length===0&&<p>请先在 DeepSeek Harness 的 Models 页面配置模型，再读取目录。</p>}{models.map((m:any)=><label className="mh-check" key={m.id}><input type="checkbox" checked={policy.modelRefs.includes(m.id)} disabled={!!m.unavailable} onChange={()=>onChange(toggleReference(policy,'modelRefs',m.id))}/>{m.label||m.model} · {m.provider}{m.unavailable&&' · '+m.unavailable}</label>)}</>}
   {axis==='harness'&&policy.harnessEnabled&&harnesses.map((h:any)=><label className="mh-check" key={h.id}><input type="checkbox" checked={policy.harnessRefs.includes(h.id)} onChange={()=>onChange(toggleReference(policy,'harnessRefs',h.id))}/>{h.name}{h.version?' · '+h.version:''}</label>)}
   {policy[axis+'Enabled']&&<details><summary>插件子额度（可选）</summary>{[['maxTrials','实验次数上限'],['softTokenLimit','用量软阈值（token）']].map(([field,label])=><label key={field}>{label}<input type="number" min="1" step="1" value={policy.limits?.[axis]?.[field]??''} placeholder="沿用活动总额度" onChange={e=>change({limits:{...policy.limits,[axis]:{...policy.limits?.[axis],[field]:e.target.value===''?null:Number(e.target.value)}}})}/></label>)}</details>}
  </fieldset>)}</div>
  {policy.modelEnabled&&policy.harnessEnabled&&<><label>组合选择方式<select aria-label="组合选择方式" value={policy.selectionMode} onChange={e=>change({selectionMode:e.target.value})}><option value="meta-select">由 Meta 在选定范围内自主组合</option><option value="pinned-pairs">只允许我指定的组合</option></select></label><p>不会自动遍历全部组合。不兼容的协议会被拒绝，并保留原因。</p>
   <div className="mh-table-wrap"><table><thead><tr><th>参考模型</th>{harnesses.filter((h:any)=>policy.harnessRefs.includes(h.id)).map((h:any)=><th key={h.id}>{h.name}</th>)}</tr></thead><tbody>{models.filter((m:any)=>policy.modelRefs.includes(m.id)).map((m:any)=><tr key={m.id}><th>{m.label||m.model}</th>{harnesses.filter((h:any)=>policy.harnessRefs.includes(h.id)).map((h:any)=>{const pair={modelRef:m.id,harnessRef:h.id},check=catalog?.compatibility?.find((x:any)=>x.modelRef===m.id&&x.harnessRef===h.id),selected=policy.pairs.some((x:any)=>x.modelRef===m.id&&x.harnessRef===h.id);return <td key={h.id} title={check?.reason}>{policy.selectionMode==='pinned-pairs'&&<input aria-label={(m.label||m.model)+' 与 '+h.name} type="checkbox" checked={selected} disabled={!!check&&check.state!=='supported'} onChange={()=>change({pairs:selected?policy.pairs.filter((x:any)=>x.modelRef!==m.id||x.harnessRef!==h.id):[...policy.pairs,pair]})}/>} {compatibilityLabels[check?.state]||'创建时核验'}{check?.reason&&<small>{check.reason}</small>}</td>})}</tr>)}</tbody></table></div></>}
  {error&&<p role="alert" className="mh-alert">{error}</p>}
 </fieldset>;
}
export function References({c,readEvidence}:any){
 const r=c.references;
 const [editing,setEditing]=useState(false),[draft,setDraft]=useState<any>(null),[revision,setRevision]=useState(0),[stopRunning,setStopRunning]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[more,setMore]=useState<any>(null);
 if(!r)return null;
 const models=Object.values(r.bindings.models||{}),harnesses=Object.values(r.bindings.harnesses||{});
 const runs=more?.items||r.runs.items,enabled=c.config.referencePolicy;
 async function save(){const problem=referenceError(draft);if(problem){setError(problem);return;}setBusy(true);try{await saveReferencePolicy(c.id,draft,revision,stopRunning);setEditing(false);setError('');}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 async function loadMore(){setBusy(true);try{const next=await api('/campaigns/'+c.id+'/references?offset='+(more?.nextOffset??r.runs.nextOffset)+'&limit=50');setMore({items:[...runs,...next.runs.items],nextOffset:next.runs.nextOffset})}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 return <section className="mh-card" aria-label="参考实验"><div className="mh-title"><h3>参考实验</h3>{!editing&&enabled&&!['finished','failed'].includes(c.state)&&<button onClick={()=>{const {revision,...policy}=r.policy;setDraft(policy);setRevision(revision);setEditing(true);setError('')}}>调整插件与范围</button>}</div>
  <p>参考模型插件：{r.policy.modelEnabled?'开启':'关闭'} · 参考 Harness 插件：{r.policy.harnessEnabled?'开启':'关闭'} · 共 {r.runs.total} 次参考实验</p>
  {editing&&<><ReferenceFields value={draft} onChange={setDraft} frozen={enabled} catalog={{models,harnesses,compatibility:r.compatibility}} disabled={busy}/><label className="mh-check"><input type="checkbox" checked={stopRunning} onChange={e=>setStopRunning(e.target.checked)}/>同时停止因本次调整失去授权的运行中实验</label><p>默认取消尚未启动的相关实验，运行中的实验按原期限完成。恢复开关不会恢复已取消实验或重置额度。</p><button disabled={busy} onClick={save}>保存调整</button> <button disabled={busy} onClick={()=>setEditing(false)}>取消</button></>}
  {error&&<p role="alert">{error}</p>}
  {r.compatibility.some((x:any)=>x.state!=='supported')&&<details><summary>组合可用性与限制</summary>{r.compatibility.filter((x:any)=>x.state!=='supported').map((x:any)=><p key={String(x.modelRef)+x.harnessRef}>{x.modelRef?(r.bindings.models[x.modelRef]?.label||x.modelRef):'固定 Solver'} × {x.harnessRef}：{compatibilityLabels[x.state]} · {x.reason}</p>)}</details>}
  {Object.entries(modes).map(([mode,label])=>{const selected=runs.filter((t:any)=>t.reference.mode===mode);return selected.length>0&&<details key={mode} open><summary>{String(label)} · 当前显示 {selected.length} 次</summary><p>{mode==='joint-reference'?'同时改变模型和 Harness；结果不能单独归因于任一维度。':'参考轨迹用于提出与验证假设。'}参考结果不参与主线候选排名或稳定完成认证。</p><div className="mh-table-wrap"><table><thead><tr><th>组合与任务</th><th>状态</th><th>官方成绩</th><th>轨迹与依据</th></tr></thead><tbody>{selected.map((t:any)=><tr key={t.id}><td>{t.reference.modelRef?(r.bindings.models[t.reference.modelRef]?.label||t.reference.modelRef):'固定 Solver'} × {t.reference.harnessRef||'执行候选'}<small>{tasks[t.task]||t.task}<br/>{t.reference.researchQuestion}</small></td><td>{states[t.state]||t.state}<small>{t.stopReason}</small></td><td>{t.score??'未评分'}<small>{number(t.usage?.totalTokens)} token</small></td><td>{c.evidence.filter((e:any)=>e.trialId===t.id).map((e:any)=><button key={e.id} onClick={()=>readEvidence?.(e.id)}>{e.kind}</button>)}{t.state==='reserved'&&<button disabled={busy} onClick={async()=>{setBusy(true);try{await cancelReferenceBatch(c.id,t.batchId,r.policy.revision)}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>取消此批待执行实验</button>}</td></tr>)}</tbody></table></div></details>})}
  {(more?more.nextOffset!==null:r.runs.nextOffset!==null)&&<button disabled={busy} onClick={loadMore}>加载更多参考实验</button>}
 </section>;
}
