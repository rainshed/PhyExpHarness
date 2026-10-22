import React,{useState,useEffect,useRef} from 'react';
import {readResearchRevision,readExcerpt} from '@phyexp/meta-workbench-client';
import {useResearch,useResource} from '@phyexp/meta-workbench-client/react';
import {date,tasks} from './common';
import {trialLabel,readableText} from '../readability.mjs';
import {ReadingLimits} from './reading-layout';

export const researchStates:any={proposed:'提出方向',testing:'正在验证',supported:'观察到支持',inconclusive:'尚无结论',failed:'尝试失败',abandoned:'已放弃'};
const kinds:any={motivation:'为什么开始尝试',observation:'实验带回的认识',turning_point:'什么改变了判断',annotation:'补充说明'};

export function Anchor({c,anchor,onEvidence}:any){
 const resource=useResource(c.id),e=resource.value;
 const round=c.tables?.rounds?.find((r:any)=>r.results?.some((t:any)=>t.id===e?.evidence?.trialId)),trial=round?.results?.find((t:any)=>t.id===e?.evidence?.trialId);
 return <section className="studio-evidence-context"><p><strong>这段证据支持：</strong>{anchor.supports}</p><button onClick={()=>resource.load(signal=>readExcerpt(c.id,anchor,signal))}>查看支持这一判断的片段 ↗</button>{resource.loading&&<p role="status">正在读取并核验原件…</p>}{resource.error&&<p role="alert">{resource.error}</p>}{e&&<>{trial&&<p>{round.versionName||round.versionLabel} · {tasks[trial.task]||trial.task} · {trialLabel(c,trial)}</p>}{e.evidence?.source?.adoption&&<p>历史设计启发 · {e.evidence.source.adoption.sourceCampaignName} · {e.evidence.source.adoption.sourceKind==='report'?'旧报告分析':'原始执行证据'}；不计入当前成绩。</p>}{e.availability==='available'?<><pre>{e.text}</pre><small>片段已与原件核对</small><details><summary>片段前后的上下文</summary><pre>{e.contextBefore}</pre><pre>{e.contextAfter}</pre></details><button onClick={()=>onEvidence(anchor.evidenceId,anchor.start)}>阅读完整原文 ↗</button></>:<p>{e.reason}</p>}</>}</section>;
}

export function ResearchArticle({row,c,onEvidence,onReport}:any){
 const r=row.record,labels:any={yes:'已观察到',no:'确认没有',unknown:'尚不清楚'};
 return <article className="studio-research-article"><p className="studio-report-lede">{readableText(r.summary)}</p><p className="studio-source-note">{researchStates[r.state]} · {row.author==='meta'?'Meta 解释':'用户补充'} · 修订 {row.revision} · 记录于 {date(row.recordedAt)}；事实截至 {date(r.factAt)}。</p>
  <ReadingLimits items={r.limitations}/>
  <div className="studio-explanation-grid">{[['problem','从什么问题出发'],['hypothesis','为什么值得尝试'],['change','希望改变什么'],['validation','用什么观察验证']].map(([key,label])=><section key={key}><h4>{label}</h4><p>{r[key]}</p></section>)}</div>
  {r.observations?.map((o:any,i:number)=><section key={i} className="studio-observation"><h4>实际观察 · {c.tables?.plugins?.find((p:any)=>p.id===o.plugin.pluginKey)?.displayName||'关联插件'}</h4><div className="studio-mechanism">{[['loaded','插件加载'],['applicable','适用条件出现'],['triggered','机制触发']].map(([k,l])=><div key={k}><small>{l}</small><strong>{labels[o[k]]}</strong></div>)}</div><p><strong>行为变化：</strong>{o.behavior}</p><p><strong>任务收益：</strong>{o.benefit}</p>{o.anchors.map((a:any,j:number)=><Anchor key={j} c={c} anchor={a} onEvidence={onEvidence}/>)}</section>)}
  {r.anchors?.map((a:any,i:number)=><Anchor key={i} c={c} anchor={a} onEvidence={onEvidence}/>)}
  {!r.anchors?.length&&!r.observations?.some((o:any)=>o.anchors.length)&&<p className="mh-muted">这条解释没有关联可定位的轨迹片段；不能仅凭文字判断效果。</p>}
  {r.reportIds?.map((id:string)=>onReport?<button key={id} onClick={()=>onReport(id)}>阅读关联报告修订 ↗</button>:null)}
  {r.nextStep&&<details><summary>当时提出的下一步</summary><p>{r.nextStep}</p><small>记录于 {date(row.recordedAt)}；当前是否已执行请查看实验记录。</small></details>}
  <details><summary>准确身份、来源与完整关联</summary><p>代码继承见版本父节点；这里保存问题启发与开发/采用关系，实际使用以实验记录为准。</p><pre>{JSON.stringify({recordId:row.recordId,revision:row.revision,candidateLinks:row.candidateLinks,originalRecord:r,...Object.fromEntries(['candidateIds','batchIds','trialIds','reportIds','decisionIds','relatedRecords','plugins'].map(k=>[k,r[k]]))},null,2)}</pre></details>
 </article>;
}

export function SavedResearch({c,reference,onEvidence,onReport}:any){
 const [revision,setRevision]=useState(reference.revision),detail=useResource(c.id+':'+reference.recordId);
 useEffect(()=>{setRevision(reference.revision)},[reference.recordId,reference.revision]);
 useEffect(()=>{detail.load(signal=>readResearchRevision(c.id,{recordId:reference.recordId,revision},signal))},[c.id,reference.recordId,revision]);
 return <>{detail.loading&&<p role="status">正在读取这次解释…</p>}{detail.error&&<p role="alert">{detail.error}</p>}{detail.value&&<><label className="studio-revision">解释修订<select value={revision} onChange={e=>setRevision(Number(e.target.value))}>{detail.value.revisions?.map((r:any)=><option key={r.revision} value={r.revision}>修订 {r.revision} · {date(r.recordedAt)}</option>)}</select></label><ResearchArticle row={detail.value} c={c} onEvidence={onEvidence} onReport={onReport}/></>}</>;
}

function ResearchEntry({row,c,onEvidence,onReport}:any){
 const [open,setOpen]=useState(false),[openedRow,setOpenedRow]=useState(row),trigger=useRef<HTMLElement|null>(null);
 const shown=open?openedRow:row,labels=(shown.candidateIds||[]).map((id:string)=>c.tables?.versions?.find((v:any)=>v.id===id)?.label).filter(Boolean);
 return <details className="studio-research-node" open={open} onToggle={e=>{const next=e.currentTarget.open;if(next&&!open)setOpenedRow(row);setOpen(next)}} onKeyDown={e=>{if(e.key==='Escape'&&open){e.stopPropagation();setOpen(false);trigger.current?.focus({preventScroll:true})}}}><summary ref={trigger as any}><small>{kinds[shown.kind]||'研究记录'}{labels.length?' · '+labels.join(' / '):''} · {date(shown.recordedAt)}</small><p>{readableText(shown.summary)}</p><span className="studio-node-state">{researchStates[shown.state]}</span><span className="studio-node-open">{open?'收起解释':'解释与依据 ↗'}</span></summary>
  {open&&<div className="studio-reading-section-body"><SavedResearch c={c} reference={openedRow} onEvidence={onEvidence} onReport={onReport}/></div>}
 </details>;
}

export function ResearchPanel({c,onEvidence,onReport,compact=false,onAll,pluginKey='',grouped=false}:any){
 const [offset,setOffset]=useState(0),[relation,setRelation]=useState('plugin'),view=useResearch(c.id,c.researchRevision,offset,pluginKey,grouped?relation:'');
 useEffect(()=>setOffset(0),[c.id,pluginKey,relation]);
 const rows=view.value?.items||[],shown=compact?rows.slice(0,3).reverse():rows;
 return <section className="studio-research-notebook" aria-label={grouped?'全部研究记录':'研究问题与转折'}>{!grouped&&<div className="studio-section-title"><div><small className="studio-kicker">RESEARCH / 认识的变化</small><h2>{compact?'研究如何走到这一步？':'相关研究记录'}</h2></div>{compact&&onAll&&<button onClick={onAll}>全部研究记录 →</button>}</div>}
  {grouped&&<><nav className="studio-research-categories" aria-label="研究记录分类">{[['plugin','与插件相关的研究'],['unlinked','尚未形成插件的尝试']].map(([id,label])=><button key={id} aria-pressed={relation===id} onClick={()=>{setOffset(0);setRelation(id)}}>{label}<span>{view.value?.relationCounts?.[id]??'…'}</span></button>)}</nav><p className="studio-research-category-note">{relation==='plugin'?'从已有插件的开发动机，看到验证观察和后续取舍。':'这里收录尚未关联到具体插件的记录，包括探索中的想法、失败或放弃的方向；各自状态以记录为准。'}</p></>}
  <p className="mh-muted">{compact?'最近保存的研究节点，按时间先后阅读。':'按记录时间倒序，保留每条记录的最新修订。'}每条反映当时的认识，详细限制与计划可展开核对。</p>
  {view.loading&&<p role="status">正在读取研究记录…</p>}{view.error&&<p role="alert">{view.error}</p>}{!view.loading&&!view.error&&!rows.length&&<p>{grouped?(relation==='plugin'?'暂时没有与插件相关的研究记录。':'暂时没有尚未形成插件的尝试记录。'):'尚未记录独立解释；已有实验和原始报告仍可查阅。'}</p>}
  <div className={compact?'studio-turning-grid':'studio-research-list'}>{shown.map((r:any)=><ResearchEntry key={r.recordId} row={r} c={c} onEvidence={onEvidence} onReport={onReport}/>)}</div>
  {!compact&&<div className="mh-actions"><button disabled={!offset||view.loading} onClick={()=>setOffset(Math.max(0,offset-20))}>上一页研究记录</button><span>共 {view.value?.total??0} 条研究记录</span><button disabled={view.loading||view.value?.nextOffset==null} onClick={()=>setOffset(view.value.nextOffset)}>下一页研究记录</button></div>}
 </section>;
}
