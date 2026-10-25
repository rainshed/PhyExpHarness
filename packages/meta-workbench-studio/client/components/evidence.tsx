import {useState,useEffect} from 'react';
import {api} from '@phyexp/meta-workbench-client';
import {useResource} from '@phyexp/meta-workbench-client/react';
import {tasks} from '../components/common';
import {resultLabel} from '../components/failure';
import {trialsFor} from '../readability.mjs';
import {SnapshotNotice} from './trial-status';


export function EvidenceIndex({c,readEvidence}:any){
 const [open,setOpen]=useState(false),[query,setQuery]=useState(''),[kind,setKind]=useState(''),[task,setTask]=useState(''),[candidateId,setCandidate]=useState(''),[offset,setOffset]=useState(0);
 const page=useResource(c.id);
 useEffect(()=>{setOffset(0)},[query,kind,task,candidateId,c.id]);
 useEffect(()=>{if(!open)return;const timer=setTimeout(()=>page.load(signal=>api(`/campaigns/${c.id}/evidence?`+new URLSearchParams({offset:String(offset),limit:'50',query,kind,task,candidateId}),undefined,signal)),200);return()=>clearTimeout(timer)},[open,c.id,offset,query,kind,task,candidateId,c.evidenceIndex?.total]);
 const rows=page.value?.items||[];
 return <details className="mh-card" onToggle={e=>setOpen(e.currentTarget.open)}><summary>高级证据检索 · 全部归档</summary>
 <p>完整目录按页读取；按版本、任务、实验编号或原始文件路径检索。</p>
 <div className="mh-grid"><label>搜索证据<input value={query} onChange={e=>setQuery(e.target.value)} placeholder="证据编号、实验编号或文件路径"/></label>
 <label>版本<select value={candidateId} onChange={e=>setCandidate(e.target.value)}><option value="">全部版本</option>{c.tables.versions.map((v:any)=><option key={v.id} value={v.id}>{v.displayName}</option>)}</select></label>
 <label>任务<select value={task} onChange={e=>setTask(e.target.value)}><option value="">全部任务</option>{c.config.tasks.map((t:string)=><option key={t} value={t}>{tasks[t]||t}</option>)}</select></label>
 <label>类型<select value={kind} onChange={e=>setKind(e.target.value)}><option value="">全部类型</option>{['official-result','trajectory-original','raw-artifact','lifecycle','historical-inspiration'].map(k=><option key={k}>{k}</option>)}</select></label></div>
 {page.loading&&<p role="status">读取目录…</p>}{page.error&&<p role="alert">{page.error}</p>}<p>{page.value?.total??c.evidenceIndex?.total??0} 条归档；当前显示 {rows.length} 条。</p>
 <div className="studio-evidence-list">{rows.map((e:any)=>{const t=trialsFor(c).find((t:any)=>t.id===e.trialId),v=c.tables.versions.find((v:any)=>v.id===t?.candidateId);return <button key={e.id} onClick={()=>readEvidence(e.id)}><strong>{v?.label||'活动'} · {tasks[t?.task]||t?.task||'活动记录'}</strong><span>{e.kind} · {t?resultLabel(t):'归档依据'}</span><small>{e.source?.archive} · {e.id}</small></button>})}</div>
 <button disabled={!offset||page.loading} onClick={()=>setOffset(Math.max(0,offset-50))}>上一页证据</button><button disabled={page.value?.nextOffset==null||page.loading} onClick={()=>setOffset(page.value.nextOffset)}>下一页证据</button></details>;
}

export function EvidenceContext({c,evidence}:any){const t=trialsFor(c).find((t:any)=>t.id===evidence.trialId),v=c.tables.versions.find((v:any)=>v.id===t?.candidateId);return <div className="studio-evidence-context">{c.historical&&<SnapshotNotice campaign={c}/>}<h3>{v?.displayName||'活动记录'}</h3><p>{tasks[t?.task]||t?.task||'所选报告或决策的归档依据'}</p>{t&&<><p><strong>{resultLabel(t)}</strong></p>{t.failure?.message&&<p>{t.failure.message}</p>}</>}<p className="mh-muted">下方为已校验的原始片段；编号与字符位置用于追溯。</p></div>}
