import {useState} from 'react';
import {api} from '@phyexp/meta-workbench-client';
import {duration,tasks} from './common';
import {FailureDetail} from './failure';
import {TrialStatus} from './trial-status';
import {trialBucket,trialLabel,trialReport} from '../readability.mjs';
export function TrialTiming({trial:t}:any){
 const conditions=t.effectiveConditions||{},timing=t.timing||t.summary?.timing||{};
 if((conditions.timePolicy||timing.timePolicy)!=='benchmark-time-v2')return null;
 const seconds=(value:any)=>typeof value==='number'&&Number.isFinite(value)?duration(value):'未记录';
 const limit=conditions.solverTimeSeconds??timing.solverTimeSeconds;
 return <p className="mh-muted">任务求解上限：{limit==null?'benchmark 未设限':seconds(limit)}；启动可用：{seconds(conditions.availableTimeSeconds??timing.availableTimeSeconds)}；求解开始时剩余：{seconds(conditions.availableTimeAtSolverStartSeconds??timing.availableTimeAtSolverStartSeconds)}。<br/>实际准备：{seconds(timing.preparationSeconds)}；求解：{seconds(timing.solverSeconds)}；评分：{seconds(timing.verifierSeconds)}；执行耗时：{seconds(timing.executionTimeSeconds)}。{conditions.interruptionRiskAtLaunch&&'启动时无法保证完整阶段窗口，可能受活动截止中断。'}</p>;
}
export function TrialList({rows,campaign={},onEvidence,onStopTrial,onReport}:any){
 const [filter,setFilter]=useState('all'),[page,setPage]=useState(0),[withdrawError,setWithdrawError]=useState('');
 const filtered=rows.filter((t:any)=>filter==='all'||trialBucket(t)===filter),size=20;
 const start=Math.min(page*size,Math.max(0,Math.floor((filtered.length-1)/size)*size));
 return <div className="studio-trials"><nav className="mh-tabs" aria-label="实验状态筛选">{[['all','全部'],['active','运行 / 启动'],['queued','排队'],['ended','已结束'],['unknown','待核实']].map(([key,label])=><button key={key} aria-pressed={filter===key} onClick={()=>{setFilter(key);setPage(0)}}>{label} {rows.filter((t:any)=>key==='all'||trialBucket(t)===key).length}</button>)}</nav>
 {withdrawError&&<p role="alert">{withdrawError}</p>}
 {!filtered.length&&<p className="mh-muted">此范围尚无实验记录。</p>}{filtered.slice(start,start+size).map((t:any)=>{const report=trialReport(campaign,t);return <section className="studio-trial" key={t.id}><div className="mh-title"><strong>{tasks[t.task]||t.task} · {trialLabel(campaign,t)}</strong></div><TrialStatus trial={t} campaign={campaign}/><FailureDetail trial={t}/><TrialTiming trial={t}/><div className="mh-actions"><button onClick={()=>onEvidence?.(t.id)}>查看本次依据</button>{report&&onReport?<button onClick={()=>onReport(report)}>阅读本轮报告</button>:<small>{campaign.historical?'报告入口不在此快照中':'本轮报告尚未归档'}</small>}{!campaign.historical&&onStopTrial&&['running','launching'].includes(t.state)&&<button onClick={()=>onStopTrial(t.id)}>终止本次实验</button>}</div>{!campaign.historical&&t.state==='reserved'&&<button onClick={async()=>{try{await api('/trials/'+t.id+'/withdraw',{reason:'用户在工作台撤回未启动实验',idempotencyKey:'withdraw:'+t.id});setWithdrawError('')}catch(e:any){setWithdrawError(e.message)}}}>撤回未启动实验</button>}<details><summary>完整实验身份与计分依据</summary><p>{t.id}</p><pre>{JSON.stringify({state:t.state,officialScore:t.score,execution:t.execution,officialResult:t.officialResult,evidenceStatus:t.evidenceStatus,assessment:t.taskAssessment,timing:t.timing,conditions:t.effectiveConditions||t.comparisonContext},null,2)}</pre></details></section>})}
 {filtered.length>size&&<div className="mh-actions"><button disabled={start===0} onClick={()=>setPage(Math.max(0,start/size-1))}>上一页实验</button><span>{start+1}–{Math.min(start+size,filtered.length)} / {filtered.length}</span><button disabled={start+size>=filtered.length} onClick={()=>setPage(start/size+1)}>下一页实验</button></div>}</div>
}
