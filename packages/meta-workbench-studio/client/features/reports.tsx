import {ResearchArticle} from '../components/research';
import {TrialList} from '../components/trial-list';
import React,{useEffect} from 'react';
import {API,number,duration,date,reasons} from '../components/common';
import {Text} from '../components/reading';
import {HarnessTables} from '../components/tables';
import {SelectionDecisions} from '../components/selection';
import {SnapshotNotice} from '../components/trial-status';
import {MetaComposition} from '../components/meta-composition';
import {comparison,trialsFor,reportGroups,reportKey,reportTitle,reportCampaign} from '../readability.mjs';

import {VersionComparison} from '../components/version-comparison';

function ReportArticle({report,w,tablesProps}:any){const a=report.reading||report.analysis,f=report.facts,c=reportCampaign(report),incomplete=report.kind==='status_summary'||report.status==='analysis_incomplete';
 const referenced=(id:string,offset=0)=>w.readContextEvidence?w.readContextEvidence(id,c,offset):w.readEvidence(id,offset);
 const contextEvidence=(id:string)=>{const e=f.evidence.find((e:any)=>e.trialId===id);if(e)referenced(e.id);else w.setNotice('此报告快照未包含该实验的归档证据。')};
 const contributions=(a.pluginContributions||[]).filter((p:any)=>p.evidenceRefs?.length || p.observed&&!p.observed.startsWith('原报告未单独评价'));
 const missing=(a.pluginContributions?.length||0)-contributions.length;
 return <article className="studio-readable-report"><div className="mh-title"><span className="mh-muted">{reportTitle(report,c.batches)} · 修订 {report.analysisRevision} · {date(report.createdAt)}</span><a href={API+'/reports/'+report.id+'/download'} download>下载完整报告 ↓</a></div><SnapshotNotice campaign={c} recordedAt={report.createdAt}/>
 <section><h2>{incomplete?'阶段摘要':'结论与决定'}</h2>{incomplete&&<p className="mh-notice">运行{['finished','failed'].includes(c.state)?'已结束':'状态见快照'}，Meta 完整分析尚未完成。以下保留已确认事实，不补写效果结论。</p>}<p className="studio-report-lede">{a.summary}</p><div className="studio-decision"><Text value={a.decision}/></div>{a.evidenceRefs?.length>0&&<div className="mh-actions">{a.evidenceRefs.map((id:string,i:number)=><button key={id} onClick={()=>referenced(id)}>查看结论依据 {i+1}</button>)}</div>}</section>
 <VersionComparison key={report.id} c={c} onEvidence={contextEvidence} compact/>
 <section><h3>成本与代价</h3><p>活动累计已确认 {number(c.usage.confirmedTokens)} token · 墙钟 {duration(c.elapsedSeconds)}。</p><p>Solver {number(f.usageByRole?.solver?.confirmedTokens)} token；Meta 设计与报告 {number(f.usageByRole?.meta?.confirmedTokens)} token。</p>{c.usage.unknownRequests>0&&<p className="mh-notice">还有 {c.usage.unknownRequests} 个请求用量待核实，未按零处理。</p>}<p>停止原因：{reasons[c.stopReason]||c.stopReason||'尚未停止'}。</p>{a.problems?.length>0&&<Text value={a.problems}/>}</section>
 <section><h3>局限与下一步</h3>{(!incomplete||a.limitations?.some?.((v:any)=>v!=='Meta 完整分析尚未完成。'))&&<Text value={a.limitations}/>} {a.hypotheses?.length>0&&<Text value={a.hypotheses}/>}<p className="mh-muted">{f.generalization}</p>{c.finishAssessment&&<p>Meta 结束依据：{c.finishAssessment.reason}</p>}</section>
 {report.researchRecords?.map((row:any)=><details key={row.id}><summary>{row.record.summary} · 解释修订 {row.revision}</summary><ResearchArticle row={row} c={c} onEvidence={referenced} onReport={w.readReport}/></details>)}
 <div className="studio-appendices"><h3>过程与追溯</h3><details><summary>过程观察与插件作用</summary><Text value={a.process||a.observations}/>{contributions.map((p:any,i:number)=><section key={i}><h4>{p.plugin}</h4><dl>{[['expected','预期作用'],['observed','实际观察'],['comparison','与对照相比'],['assessment','判断']].map(([k,title])=><React.Fragment key={k}><dt>{title}</dt><dd>{p[k]}</dd></React.Fragment>)}</dl>{p.evidenceRefs?.map((id:string,j:number)=><button key={id} onClick={()=>referenced(id)}>作用依据 {j+1}</button>)}</section>)}{missing>0&&<details><summary>{missing} 项插件未单独记录贡献</summary><Text value={(a.pluginContributions||[]).filter((p:any)=>!contributions.includes(p)).map((p:any)=>p.plugin)}/></details>}</details>
 <details><summary>Meta 选择历史与比较局限</summary><SelectionDecisions decisions={f.selectionDecisions} tables={report.tables} readEvidence={referenced}/></details>
 <details><summary>Meta 运行、资源与停止审查</summary><MetaComposition campaign={c} composition={f.metaComposition} observations={f.metaObservations} sessions={f.metaSessions} reviews={f.stopReviews}/></details>
 <details><summary>实验状态与故障诊断</summary><TrialList campaign={c} rows={trialsFor(c).filter((t:any)=>!report.batchId||report.tables.rounds.find((r:any)=>r.id===report.batchId)?.results.some((r:any)=>r.id===t.id))} onEvidence={contextEvidence}/></details>
 <details><summary>原始三表 · 插件、版本与轮次</summary><HarnessTables tables={report.tables} {...tablesProps} campaign={c} onStopTrial={undefined} onRename={undefined} onEvidence={contextEvidence}/></details>
 <details><summary>完整报告、原分析与技术身份</summary><p className="mh-muted">{a.source} {report.revisionReason} {report.evaluationNotice}</p><pre className="mh-prose">{report.markdown}</pre><pre>{JSON.stringify(report.analysis,null,2)}</pre><small>报告 {report.id} · 事实摘要 {report.factsSha256}</small></details></div></article>
}

export function Reports({w,tablesProps}:any){const {c,report,reportLoading,reportError,readReport}=w;const groups=reportGroups(c.reports,c.batches),group=groups.find(g=>report&&reportKey(g[0])===reportKey(report));
 useEffect(()=>{if(!report&&!reportLoading&&!reportError&&groups.length)readReport(groups[0][0].id)},[c.id]);
 return <div className="studio-report-layout"><aside className="studio-report-list" aria-label="报告列表">{groups.map(rows=>{const r=rows[0];return <button key={r.id} className={report&&reportKey(report)===reportKey(r)?'selected':''} onClick={()=>readReport(r.id)}><strong>{reportTitle(r,c.batches)}</strong><small>{r.status==='analysis_incomplete'?'已确认事实，完整分析未完成':'实验观察、决定与局限'}</small><small>{date(r.createdAt)} · 最新修订 {r.analysisRevision}</small></button>})}</aside><section className="mh-card studio-report-body"><label className="studio-report-picker">选择报告<select aria-label="选择报告" value={group?.[0]?.id||''} onChange={e=>e.target.value&&readReport(e.target.value)}><option value="">选择报告…</option>{groups.map(rows=><option key={rows[0].id} value={rows[0].id}>{reportTitle(rows[0],c.batches)}</option>)}</select></label>{group&&<label className="studio-revision">报告修订<select aria-label="选择报告修订" value={report?.id||''} onChange={e=>readReport(e.target.value)}>{group.map((r:any,i:number)=><option key={r.id} value={r.id}>修订 {r.analysisRevision}{i===0?' · 最新':''} · {date(r.createdAt)}</option>)}</select></label>}{reportLoading&&<p role="status">正在读取报告…</p>}{reportError&&<p role="alert" className="mh-alert">{reportError}</p>}{!groups.length&&<p>Meta 提交分析后，报告会出现在这里。</p>}{report&&<ReportArticle report={report} w={w} tablesProps={tablesProps}/>}</section></div>;
}
