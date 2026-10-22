import React,{useEffect} from 'react';
import {api} from '@phyexp/meta-workbench-client';
import {useResource,useResearch} from '@phyexp/meta-workbench-client/react';
import {ResearchPanel} from '../components/research';
import {number,duration,date} from '../components/common';
import {activityProgress} from '../components/trial-status.mjs';
import {VersionComparison} from '../components/version-comparison';
import {PageIntro,ReadingLimits} from '../components/reading-layout';
import {reportCampaign,reportGroups,readableText} from '../readability.mjs';

export function Overview({w,tablesProps}:any){
 const {c,navigate}=w,versions=c.tables?.versions||[],decision=c.selectionDecisions?.at(-1);
 const chosen=versions.find((v:any)=>v.id===(c.finalCandidateId||c.retainedCandidateId));
 const research=useResearch(c.id,c.researchRevision),recent=research.value?.items?.[0];
 const report=useResource(c.id);
 const ended=['finished','failed'].includes(c.state);
 const latest=ended?reportGroups(c.reports,c.batches).find(rows=>rows[0].kind==='final'||rows[0].kind==='status_summary')?.[0]:null;
 useEffect(()=>{if(latest)report.load(signal=>api('/reports/'+latest.id,undefined,signal));else report.clear()},[c.id,latest?.id]);
 const saved=report.value?.id===latest?.id?report.value:null;
 const summary=saved?.analysis?.brief||recent?.summary;
 const limits=saved?.analysis?.brief?saved.analysis.limitations:recent?.limitations;
 const stamp=saved?.analysis?.brief?reportCampaign(saved).snapshotAt:recent?.factAt;
 const next=ended?null:recent?.nextStep;
 return <>
  <PageIntro eyebrow="EVOLUTION / 研究方向与当前判断" title="这次进化，为什么这样走？">先理解发现与选择，再看每个版本的实验表现。</PageIntro>
  <section className="studio-reading-hero" aria-label="研究结论与当前选择">
   <div className="studio-hero-findings"><small className="studio-kicker">{saved?.analysis?.brief?'最新报告中的结论':'最近保存的研究认识'}</small>
    {research.loading||report.loading?<p role="status">正在读取研究概述…</p>:<p className="studio-hero-lede">{readableText(summary)||'尚未记录独立的研究概述。已有的实验结果和原始报告仍可查阅。'}</p>}
    {(report.error||research.error)&&<p role="alert">概述读取未完成：{report.error||research.error}</p>}
    <ReadingLimits items={limits} compact/>
    {summary&&<p className="studio-source-note">{saved?.analysis?.brief?'来自总报告 · 修订 '+saved.analysisRevision:'来自研究记录 · 修订 '+recent.revision}{stamp!=null?' · '+date(stamp):''}。实验进度见下方实时矩阵。</p>}
    {saved&&<button className="studio-text-link" onClick={()=>w.readReport(saved.id)}>阅读这份报告与依据 ↗</button>}
   </div>
   <div className="studio-hero-choice"><small className="studio-kicker">{c.finalCandidateId?'最终保留':'当前选择'}</small><h2>{chosen?.displayName||'尚未选择版本'}</h2>
    <p>{readableText(decision?.summary)||'等待 Meta 保存选择理由；最新候选仍可在矩阵中查看。'}</p>
    {decision&&<small>决定于 {date(decision.createdAt)} · 选择不代表稳定收益已证实</small>}
    <button className="primary" onClick={()=>navigate('compare','decision')}>为什么保留这一版？ →</button>
   </div>
  </section>
  <VersionComparison c={c} compact onEvidence={tablesProps.onEvidence} onStopTrial={tablesProps.onStopTrial} onReport={w.readReport}/>
  <ResearchPanel c={c} compact onEvidence={w.readEvidence} onReport={w.readReport} onAll={()=>navigate('lab','research')}/>
  <section className="studio-next-step"><span aria-hidden="true">↗</span><div><small>{ended?'接下来如何阅读':'最近记录的验证计划'}</small><p>{ended?'查看最终选择的依据，或从任务结果回到每次实验。后续研究方向保留在报告中。':next||'尚未记录下一步研究计划。'}</p>{!ended&&next&&<small>计划记录于 {date(recent.recordedAt)}；是否已启动以任务矩阵为准。</small>}</div><button onClick={()=>ended&&latest?w.readReport(latest.id):navigate('rounds')}>{ended&&latest?'阅读最终报告':'查看实验记录'} →</button></section>
  <div className="studio-path-grid"><button onClick={()=>navigate('lab')}><strong>一个插件为什么被写出来？</strong><span>从用途、动机，一直看到具体来源。</span></button><button onClick={()=>navigate('compare','decision')}><strong>为什么选它，而没有选另一个？</strong><span>查看备选、代价和重新考虑的条件。</span></button></div>
  <section className="studio-run-strip" aria-label="运行概况"><span>{activityProgress(c)}</span><span>{c.counts.startedTrials} 次已启动实验 · {c.counts.rounds} 轮</span><span>{number(c.usage.confirmedTokens)} token 已确认 · {duration(c.elapsedSeconds)}</span><button onClick={()=>navigate('meta')}>用量、配置与运行详情 →</button>{c.usage.unknownRequests>0&&<strong>仍有 {c.usage.unknownRequests} 个请求用量待核实</strong>}</section>
 </>;
}
