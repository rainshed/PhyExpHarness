import React from 'react';
import {trialStage} from './trial-status.mjs';
export const resultLabel=(t:any)=>trialStage(t).label;
const scoring:any={not_run:'官方评分未运行',failed:'官方评分器失败',completed:'已有官方评分',unknown:'评分阶段尚不能确认',pending:'等待评分'};
const stages:any={admission:'平台请求准入',model:'模型请求',execution:'实验执行',verifier:'官方评分',collection:'结果收集',startup:'实验启动',environment:'容器环境准备',supervision:'执行监督'};
export function TransportDetail({observed:o}:any){const t=o?.transport;if(!t)return null;
 return <div><p>模型连接：{t.actualTransport||'尚未观察到传输方式'}；协议响应：{t.protocolStarted===true?'已开始':t.protocolStarted===false?'尚未观察到开始':'未记录'}。模型内容 {o.responseContentBytes??o.responseBytes??'未记录'} 字节，不能据此推断连接尚未返回协议事件。</p>
 {t.connectionId&&<p>连接：{t.connectionId}；发起请求时已建立 {Math.round((t.connectionAgeMs||0)/1000)} 秒；本连接第 {t.connectionRequestCount} 次请求。</p>}
 {t.closeCode!==undefined&&<p>连接关闭码：{t.closeCode}；正常关闭：{t.wasClean?'是':'否'}。关闭码本身不确定责任归属。</p>}
 {t.httpStatus!==undefined&&<p>HTTP 状态：{t.httpStatus}{o.statusSource==='request-transport'?'；错误分类采用本请求的传输状态':''}。</p>}
 {t.lastProtocolEvent&&<p>最后协议事件：{t.lastProtocolEvent}</p>}
 {t.fallbackToSse&&<p>本次请求曾从 WebSocket 回退到 SSE。</p>}</div>;
}
function RecoveryDetail({trial:t}:any){
 const r=t.requestRecovery,b=t.containerTransport;
 return <>
  {r?.failedRequests>0&&<details><summary>模型请求曾失败 {r.failedRequests} 次；确认恢复 {r.recoveredRequests??0} 次</summary>
   <p>恢复记录保留；任务完成分按最终结果计算。</p>
   <ul>{r.failures?.map((f:any,i:number)=><li key={f.requestId||i}>{f.categoryLabel||'模型请求链路'} · {f.message||f.code}；{f.recoveredBy?'已确认恢复':'未确认恢复'}{f.requestId&&<small>（请求 {f.requestId}）</small>}</li>)}</ul>
  </details>}
  {b?.issues?.length>0&&<details><summary>容器连接记录：{b.verificationBlocked?'存在阻断评分的故障':'异常未阻断评分'}</summary>
   <p>完整执行结果与回传连接分别记录；已完成的命令不会自动重放。</p>
   <ul>{b.issues.map((issue:any,i:number)=><li key={i}>调用 {issue.callId} · {issue.executionState==='completed'?'执行结果已记录':issue.executionState==='running'?'执行结果未确认':issue.executionState==='rejected'?'命令被拒绝':'尚未执行'}；{issue.blocksVerification?'阻断评分':issue.recoveredBy?'后续连接已恢复':'连接异常保留为警告'}。</li>)}</ul>
   {b.evidence&&<p>归档依据：{b.evidence}</p>}
  </details>}
 </>;
}
export function FailureDetail({trial:t}:any){
 const d=t.failure,a=t.diagnosis;
 const official=<p>官方评分：{t.score==null?'未评分':String(t.score)}。{scoring[t.scoringStatus]||scoring.unknown}；任务完成分：{t.taskAssessment?.score??'不计入'}。</p>;
 const attribution=a?.category&&a.category!=='none'?<p><strong>{a.categoryLabel}</strong>。{a.causeNote} {a.impactLabel}。</p>:d?.categoryLabel?<p><strong>{d.categoryLabel}</strong>。{d.causeNote}</p>:null;
 return <>{attribution}<RecoveryDetail trial={t}/>
  {d?<details><summary>查看失败原因与依据</summary><p>{d.message}。</p>{official}
   <p>发生阶段：{stages[d.stage]||'尚未确认'}</p>
   <p>诊断来源：{d.source==='historical-artifact-analysis'?'根据历史归档追加的系统诊断；原始记录与分析保留':d.source==='controller'?'后台监督记录':'执行宿主记录'}</p>
   <details><summary>技术依据</summary><p>原因代码：{d.code}</p><TransportDetail observed={d.observed}/>
    {d.termination&&<p>终止方式：{d.termination}</p>}{d.detectedAt&&<p>记录时间：{d.detectedAt}</p>}
    {d.requestId&&<p>请求：{d.requestId}</p>}{d.observed&&<pre>{JSON.stringify(d.observed,null,2)}</pre>}
    {d.limits&&<pre>{JSON.stringify(d.limits,null,2)}</pre>}{d.evidence&&<p>归档依据：{d.evidence}</p>}
    {d.secondaryCodes?.length>0&&<p>后续清理或收集事件：{d.secondaryCodes.join('、')}</p>}
   </details>
  </details>:t.taskAssessment&&<details><summary>查看评分依据</summary>{official}<p>判定原因：{t.taskAssessment.reason}</p></details>}
 </>;
}
