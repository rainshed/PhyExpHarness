import {useEffect,useState} from 'react';
import {readSelection} from '@phyexp/meta-workbench-client';
import {useResource} from '@phyexp/meta-workbench-client/react';
import {TaskEvaluation} from './outcomes';
import {SnapshotNotice} from './trial-status';
import {ResearchArticle} from './research';
import {date,number,duration} from './common';
import {versionCost,comparison} from '../readability.mjs';
function DecisionCost({rows}:any){const cost=versionCost(rows);return <p className="mh-muted">{cost.tokens==null?'确认用量未记录':number(cost.tokens)+' token 已确认'} · 用量记录 {cost.recorded}/{cost.attempts} · {cost.seconds==null?'耗时未记录':duration(cost.seconds)+' 单次耗时合计'} · 完整耗时 {cost.timed}/{cost.attempts} · 未知请求 {cost.unknown} / 预留 {number(cost.unknownReserved)} token。仅含这些实验，不含 Meta；耗时合计不等于活动墙钟。</p>}
function Decision({row,campaignId,tables,readEvidence,onReport,initial}:any){
 const [open,setOpen]=useState(initial),resource=useResource(campaignId||row.id);
 useEffect(()=>{if(open&&row.detailsAvailable&&!resource.value&&campaignId)resource.load(signal=>readSelection(campaignId,row.id,signal))},[open,row.id]);
 const d=row.detailsAvailable?resource.value:row,names=new Map((tables?.versions||[]).map((v:any)=>[v.id,v.displayName]));
 const snapshot={historical:true,snapshotAt:row.createdAt};
 const frozenNames=new Map((d?.consideredSnapshot?.candidates||[]).map((v:any)=>[v.id,v.snapshotDisplayName||v.displayName||v.id]));
 const name=(id:string)=>frozenNames.get(id)||names.get(id)||id;
 const compareSnapshot=d?.consideredSnapshot&&{trials:d.consideredSnapshot.trials,config:{tasks:Object.keys(d.consideredSnapshot.taskEvaluation.byTask||{})}};
 const historicalTrials=d?.consideredSnapshot?.trials||d?.assessment?.trials||[];
 const evidenceContext={...snapshot,trials:historicalTrials,tables:{versions:(tables?.versions||[]).map((v:any)=>({...v,displayName:name(v.id)})),rounds:(tables?.rounds||[]).map((r:any)=>({...r,results:historicalTrials.filter((t:any)=>t.batchId===r.id)}))}};
 const evidence=(id:string,offset=0)=>campaignId?readEvidence(id,evidenceContext,offset):readEvidence(id,offset);
 return <details open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary>{date(row.createdAt)} · {name(row.candidateId)}</summary><p className="studio-decision">{row.summary||d?.reason||'未记录独立的简短选择结论。'}</p>{row.limitations?.length>0&&<p className="mh-notice">局限：{row.limitations.join('；')}</p>}<SnapshotNotice campaign={snapshot}/>{resource.loading&&<p role="status">正在读取当时的决定…</p>}{resource.error&&<p role="alert">{resource.error}</p>}{d&&<><p>此前保留：{name(d.previousCandidateId)||'尚未选择'}；本次选定：{name(d.candidateId)}。</p><p><strong>选择理由：</strong>{d.reason}</p><p><strong>权衡：</strong>{d.tradeoffs}</p><p><strong>重新考虑的条件：</strong>{d.reconsiderWhen}</p><h4>明确考虑过的备选</h4>{d.alternatives?.length?d.alternatives.map((a:any)=><div key={a.candidateId}><p><strong>{name(a.candidateId)}</strong>：{a.reason}</p>{a.evidenceRefs.map((id:string)=><button key={id} onClick={()=>evidence(id)}>核对未选依据</button>)}</div>):<p className="mh-muted">{d.alternatives?'本次未列出其他备选。':'未记录备选分析；不能据此认定其他版本已被否决。'}</p>}<details><summary>当时的表现、成本与比较限制</summary>{d.assessment?.comparisonLimitations?.map((s:string,i:number)=><p key={i}>{s}</p>)}{d.consideredSnapshot?Object.entries(d.consideredSnapshot.taskEvaluation.byCandidate).map(([id,stats]:any)=><section key={id}><h4>{name(id)}</h4><p>{comparison(compareSnapshot,id,d.candidateId).label}：{comparison(compareSnapshot,id,d.candidateId).reasons.join('；')}</p><TaskEvaluation value={stats} rows={d.consideredSnapshot.trials.filter((t:any)=>t.candidateId===id)} campaign={snapshot} details/><DecisionCost rows={d.consideredSnapshot.trials.filter((t:any)=>t.candidateId===id)}/></section>):<TaskEvaluation value={d.assessment?.taskEvaluation?.candidate} rows={d.assessment?.trials||[]} campaign={snapshot} details/>}<p>活动当时已确认 {number(d.usage?.confirmedTokens)} token；未知请求 {d.usage?.unknownRequests??'未记录'}；未知预留 {number(d.usage?.unknownReservedTokens)} token。</p></details>{d.researchRecords?.map((r:any)=><details key={r.id}><summary>{r.record.summary} · 当时的解释修订 {r.revision}</summary><ResearchArticle row={r} c={{id:campaignId||d.campaignId,tables}} onEvidence={evidence} onReport={onReport}/></details>)}{d.evidenceRefs?.map((id:string)=><button key={id} onClick={()=>evidence(id)}>核对选择原始依据 ↗</button>)}<details><summary>决策身份与完整快照</summary><pre>{JSON.stringify(d,null,2)}</pre></details></>}</details>
}
export function SelectionDecisions({decisions=[],tables,readEvidence,campaignId,onReport}:any){
 const [count,setCount]=useState(10);
 if(!decisions.length)return <p className="mh-muted">尚未记录版本选择。</p>;
 return <section className="mh-card"><h3>为什么选择这个版本</h3><p className="mh-muted">以下是决定当时的理由与事实；最新实验表现见任务矩阵。选择表示 Meta 的取舍。</p>{[...decisions].reverse().slice(0,count).map((d:any,i:number)=><Decision key={d.id} row={d} campaignId={campaignId} tables={tables} readEvidence={readEvidence} onReport={onReport} initial={i===0}/>)}{count<decisions.length&&<button onClick={()=>setCount(count+10)}>查看更多历史决定</button>}</section>
}
