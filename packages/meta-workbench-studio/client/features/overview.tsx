import React from 'react';
import {ResearchPanel} from '../components/research';
import {Badge,Metric,number,duration,date,short,tasks} from '../components/common';
import {ProgressNotice,TrialStatus} from '../components/trial-status';
import {activityProgress} from '../components/trial-status.mjs';
import {SelectionDecisions} from '../components/selection';
import {VersionComparison} from '../components/version-comparison';
import {RoundRecords} from '../components/round-records';
export function Metrics({c}:any){return <div className="mh-metrics studio-metrics"><Metric label="已受理轮次" value={`${c.counts.rounds} / ${c.config.maxRounds??'不限'}`} note="每个受理批次计一轮，包含 H0"/><Metric label="已启动实验" value={`${c.counts.startedTrials} / ${c.config.maxTrials??'不限'}`} note={activityProgress(c)}/><Metric label="已确认用量" value={number(c.usage.confirmedTokens)} note={c.config.softTokenLimit==null?'token 不限，持续计量':`软阈值 ${number(c.config.softTokenLimit)} token`}/><Metric label={c.state==='finished'?'实际耗时':'已用时间'} value={duration(c.elapsedSeconds)} note={c.state==='finished'?`结束于 ${date(c.finishedAt)}`:`剩余 ${duration(c.remainingSeconds)}`}/></div>}

export function Overview({w,setTable,tablesProps}:any){const {c,navigate}=w;const versions=c.tables?.versions||[];
 const chosen=versions.find((v:any)=>v.id===(c.finalCandidateId||c.retainedCandidateId)),latest=versions.at(-1);
 const current=c.trials.filter((t:any)=>['launching','running'].includes(t.state));
 const status=c.state==='draft'?(w.h0Ready?'基线已就绪，等待启动':'准备任务环境与执行基线'):c.state==='paused'?'新工作已暂停':c.state==='closing'?'正在归集结果并收尾':c.state==='finished'?'活动已结束':c.state==='failed'?'活动失败，请查看后台动态':c.metaSessions.at(-1)?.state==='needs_attention'?'Meta 需要处理，请查看后台动态':c.metaSessions.at(-1)?.state==='recovering'?'Meta 正在恢复会话':current.length?'正在等待实验结果':c.metaSessions.some((s:any)=>s.state==='running')?'Meta 正在推进活动':'等待后台工作';
 return <><ResearchPanel c={c} compact onEvidence={w.readEvidence} onReport={w.readReport}/><Metrics c={c}/><ProgressNotice campaign={c}/><div className="studio-summary-grid"><section className="mh-card"><div className="studio-card-heading"><h3>当前进展</h3><Badge value={c.state}/></div><div className="studio-card-body"><h2>{status}</h2>{current.length?<ul className="studio-current">{current.map((t:any)=><li key={t.id}><span>{tasks[t.task]||t.task||short(t.id)}</span><TrialStatus trial={t} campaign={c}/></li>)}</ul>:<p className="mh-muted">{c.operations.some((o:any)=>o.state==='failed')?'后台操作失败，请查看 Meta 运行中的具体原因。':'具体状态与进度以后台回执为准。'}</p>}</div><div className="studio-card-footer"><span>{c.counts.activeTrials} 次在途 · {c.counts.reservedTrials} 次待执行</span><button onClick={()=>navigate('meta')}>查看后台动态 →</button></div></section>
 <section className="mh-card"><div className="studio-card-heading"><h3>{c.finalCandidateId?'最终冻结版本':'当前保留版本'}</h3>{chosen&&<span className="mh-badge">{chosen.label}</span>}</div><div className="studio-card-body"><h2>{chosen?.displayName||'尚未选择'}</h2><p className="mh-muted">{chosen?.plugins.length?chosen.plugins.map((p:any)=>c.tables.plugins.find((x:any)=>x.id===p.pluginId)?.displayName||p.pluginId).join(' · '):chosen?'原始执行基线，无额外插件。':'等待 Meta 根据已有证据作出选择。'}</p><p>{c.selectionDecisions?.at(-1)?.summary||'未记录独立的简短选择结论；可展开当时理由。'}</p><p className="mh-muted">最新候选：{latest?.displayName||'暂无'}{!c.finalCandidateId&&' · 尚未冻结最终版本'}</p></div><div className="studio-card-footer"><span>选择不代表因果提升已证实</span><button onClick={()=>{navigate('compare')}}>查看版本与依据 →</button></div></section></div>
 <VersionComparison c={c} compact onEvidence={tablesProps.onEvidence} onStopTrial={tablesProps.onStopTrial} onReport={w.readReport} onVersion={()=>navigate('lab')}/>
 <RoundRecords c={c} tablesProps={tablesProps} limit={3}/><button className="studio-all-rounds" onClick={()=>navigate('rounds')}>查看全部实验记录 →</button>
 <div className="mh-notice">在途预留 {number(c.usage.inflightReservedTokens)} token · 未知请求 {c.usage.unknownRequests} 个 · 保守预留 {number(c.usage.unknownReservedTokens)} token。未知用量未按零处理；收尾预留包含在总量内。</div>
 <div className="studio-section-title"><h3>哪个版本在哪些任务上更好？</h3><button onClick={()=>navigate('compare')}>按版本与任务比较 →</button></div>
 {c.comparisonIssues?.length>0&&<p className="mh-notice">比较条件有差异或缺失，尚未证明环境一致。不能据此认定插件带来了可靠提升。</p>}
 <details><summary>Meta 版本选择与依据</summary><SelectionDecisions campaignId={c.id} decisions={c.selectionDecisions} tables={c.tables} readEvidence={w.readEvidence}/></details>
 </>;
}
