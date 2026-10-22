import React,{useEffect,useState} from 'react';
import {readSelection} from '@phyexp/meta-workbench-client';
import {useResource} from '@phyexp/meta-workbench-client/react';
import {TaskEvaluation} from './outcomes';
import {SnapshotNotice} from './trial-status';
import {ResearchArticle} from './research';
import {ReadingLimits,ReadingSection} from './reading-layout';
import {date,number,duration} from './common';
import {versionCost,comparison,readableText} from '../readability.mjs';

function DecisionCost({rows}:any){
 const cost=versionCost(rows);
 return <p className="mh-muted">{cost.tokens==null?'确认用量未记录':number(cost.tokens)+' token 已确认'} · 用量记录 {cost.recorded}/{cost.attempts} · {cost.seconds==null?'耗时未记录':duration(cost.seconds)+' 单次耗时合计'} · 完整耗时 {cost.timed}/{cost.attempts} · 未知请求 {cost.unknown} / 预留 {number(cost.unknownReserved)} token。仅含这些实验，不含 Meta；耗时合计不等于活动墙钟。</p>;
}

function Decision({row,campaignId,tables,readEvidence,onReport}:any){
 const resource=useResource((campaignId||'snapshot')+':'+row.id);
 useEffect(()=>{if(row.detailsAvailable&&campaignId)resource.load(signal=>readSelection(campaignId,row.id,signal))},[campaignId,row.id]);
 const d=row.detailsAvailable?resource.value:row;
 const frozenNames=new Map((d?.consideredSnapshot?.candidates||[]).map((v:any)=>[v.id,v.snapshotDisplayName||v.displayName||v.id]));
 const names=new Map((tables?.versions||[]).map((v:any)=>[v.id,v.displayName]));
 const name=(id:string)=>frozenNames.get(id)||names.get(id)||id;
 const snapshot={historical:true,snapshotAt:row.createdAt};
 const compareSnapshot=d?.consideredSnapshot&&{trials:d.consideredSnapshot.trials,config:{tasks:Object.keys(d.consideredSnapshot.taskEvaluation.byTask||{})}};
 const historicalTrials=d?.consideredSnapshot?.trials||d?.assessment?.trials||[];
 const evidenceContext={...snapshot,trials:historicalTrials,tables:{versions:(tables?.versions||[]).map((v:any)=>({...v,displayName:name(v.id)})),rounds:(tables?.rounds||[]).map((r:any)=>({...r,results:historicalTrials.filter((t:any)=>t.batchId===r.id)}))}};
 const evidence=(id:string,offset=0)=>campaignId?readEvidence(id,evidenceContext,offset):readEvidence(id,offset);
 return <article className="studio-choice-story">
  <p className="studio-source-note">决定于 {date(row.createdAt)} · {name(row.candidateId)}。以下保留当时的理由，{campaignId?'最新结果见任务矩阵':'当前结果请查看活动的版本对比'}。</p>
  <p className="studio-decision">{readableText(row.summary||d?.reason)||'未记录独立的简短选择结论。'}</p>
  <ReadingLimits items={row.limitations||d?.limitations}/>
  {resource.loading&&<p role="status">正在读取当时的决定…</p>}{resource.error&&<p role="alert">{resource.error}</p>}
  {d&&<>
   <div className="studio-reason-grid">{[['reason','01','为什么选择它'],['tradeoffs','02','接受了什么代价'],['reconsiderWhen','03','什么时候重新考虑']].map(([key,n,title])=><section key={key}><small>{n}</small><h3>{title}</h3><p>{readableText(d[key])||'当时未记录。'}</p></section>)}</div>
   <section className="studio-alternatives"><h3>其他版本为什么暂不保留？</h3>{d.alternatives?.length?<div className="studio-alternative-grid">{d.alternatives.map((a:any)=><article key={a.candidateId}><small>明确考虑过的备选</small><h4>{name(a.candidateId)}</h4><p>{readableText(a.reason)}</p>{a.evidenceRefs.map((id:string,i:number)=><button key={id} onClick={()=>evidence(id)}>查看 {name(a.candidateId)} 的未选依据 {i+1} ↗</button>)}</article>)}</div>:<p className="mh-muted">{d.alternatives?'本次没有列出其他备选。':'当时没有记录备选分析；其他版本不因此被视为已否决。'}</p>}</section>
   <ReadingSection number="↳" title="核对当时的表现与成本" description="包含全部相关尝试、比较限制，以及决定时的结果快照。">
    <SnapshotNotice campaign={snapshot}/><p>此前保留：{name(d.previousCandidateId)||'尚未选择'}；本次选定：{name(d.candidateId)}。</p>
    {d.assessment?.comparisonLimitations?.map((s:string,i:number)=><p key={i}>{s}</p>)}
    {d.consideredSnapshot?Object.entries(d.consideredSnapshot.taskEvaluation.byCandidate).map(([id,stats]:any)=><section key={id}><h4>{name(id)}</h4><p>{comparison(compareSnapshot,id,d.candidateId).label}：{comparison(compareSnapshot,id,d.candidateId).reasons.join('；')}</p><TaskEvaluation value={stats} rows={d.consideredSnapshot.trials.filter((t:any)=>t.candidateId===id)} campaign={snapshot} details/><DecisionCost rows={d.consideredSnapshot.trials.filter((t:any)=>t.candidateId===id)}/></section>):<TaskEvaluation value={d.assessment?.taskEvaluation?.candidate} rows={d.assessment?.trials||[]} campaign={snapshot} details/>}
    <p>活动当时已确认 {number(d.usage?.confirmedTokens)} token；未知请求 {d.usage?.unknownRequests??'未记录'}；未知预留 {number(d.usage?.unknownReservedTokens)} token。</p>
   </ReadingSection>
   <ReadingSection number="↳" title="这一决定依据了哪些研究？" description="打开当时引用的解释修订，再定位对应实验与原文。">
    {d.researchRecords?.map((r:any)=><details key={r.id}><summary>{r.record.summary} · 当时的解释修订 {r.revision}</summary><ResearchArticle row={r} c={{id:campaignId||d.campaignId,tables:evidenceContext.tables}} onEvidence={evidence} onReport={onReport}/></details>)}
    {d.evidenceRefs?.map((id:string,i:number)=><button key={id} onClick={()=>evidence(id)}>核对选择的原始依据 {i+1} ↗</button>)}
   </ReadingSection>
   <details><summary>决定身份与完整快照</summary><pre>{JSON.stringify(d,null,2)}</pre></details>
  </>}
 </article>;
}

function HistoricalDecision({row,...props}:any){
 const [open,setOpen]=useState(false);
 return <details className="studio-history-decision" open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary>{date(row.createdAt)} · {row.summary||'当时的版本选择'}</summary>{open&&<Decision row={row} {...props}/>}</details>;
}

export function SelectionDecisions({decisions=[],tables,readEvidence,campaignId,onReport,title,emptyText}:any){
 const [count,setCount]=useState(10),ordered=[...decisions].sort((a,b)=>b.createdAt-a.createdAt);
 if(!ordered.length)return <p className="mh-muted">{emptyText||'尚未记录版本选择；任务结果仍可查看。'}</p>;
 const props={tables,readEvidence,campaignId,onReport};
 return <section tabIndex={-1} data-reading-anchor="decision" className="studio-selection-reading" aria-label="版本选择与取舍"><div className="studio-section-title"><div><small className="studio-kicker">DECISION / 理由与取舍</small><h2>{title||(campaignId?'为什么现在保留这一版？':'为什么当时保留这一版？')}</h2></div></div><Decision key={ordered[0].id} row={ordered[0]} {...props}/>
  {ordered.length>1&&<ReadingSection number="↳" title="此前的选择如何变化？" description="每次决定保留当时的理由、名称和事实。">{ordered.slice(1,count).map((d:any)=><HistoricalDecision key={d.id} row={d} {...props}/>)}{count<ordered.length&&<button onClick={()=>setCount(count+10)}>查看更多历史决定</button>}</ReadingSection>}
 </section>;
}
