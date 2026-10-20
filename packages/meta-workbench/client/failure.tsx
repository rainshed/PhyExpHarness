import React from 'react';
import {trialStage} from './trial-status.mjs';
export const resultLabel=(t:any)=>trialStage(t).label;
const scoring:any={not_run:'官方评分未运行',failed:'官方评分器失败',completed:'已有官方评分',unknown:'评分阶段尚不能确认',pending:'等待评分'};
const stages:any={admission:'平台请求准入',model:'模型请求',execution:'实验执行',verifier:'官方评分',collection:'结果收集',startup:'实验启动',supervision:'执行监督'};
export function TransportDetail({observed:o}:any){const t=o?.transport;if(!t)return null;
 return <div><p>模型连接：{t.actualTransport||'尚未观察到传输方式'}；协议响应：{t.protocolStarted===true?'已开始':t.protocolStarted===false?'尚未观察到开始':'未记录'}。模型内容 {o.responseContentBytes??o.responseBytes??'未记录'} 字节，不能据此推断连接尚未返回协议事件。</p>
 {t.connectionId&&<p>连接：{t.connectionId}；发起请求时已建立 {Math.round((t.connectionAgeMs||0)/1000)} 秒；本连接第 {t.connectionRequestCount} 次请求。</p>}
 {t.closeCode!==undefined&&<p>连接关闭码：{t.closeCode}；正常关闭：{t.wasClean?'是':'否'}。关闭码本身不确定责任归属。</p>}
 {t.lastProtocolEvent&&<p>最后协议事件：{t.lastProtocolEvent}</p>}
 {t.fallbackToSse&&<p>本次请求曾从 WebSocket 回退到 SSE。</p>}</div>;
}
export function FailureDetail({trial:t}:any){const d=t.failure;const r=t.requestRecovery;if(!d)return r?.failedRequests>0?<p>模型请求曾失败 {r.failedRequests} 次；确认恢复 {r.recoveredRequests} 次。任务按最终结果计分，调用记录保留。</p>:null;
 return <details><summary>查看失败原因与依据</summary><p>{d.message}。{scoring[t.scoringStatus||d.scoringStatus]||scoring.unknown}。</p>{r?.failedRequests>0&&<p>模型请求失败 {r.failedRequests} 次；确认恢复 {r.recoveredRequests} 次。任务完成分按最终结果计算。</p>}<p>发生阶段：{stages[d.stage]||'尚未确认'}</p><p>诊断来源：{d.source==='historical-artifact-analysis'?'根据历史归档追加的系统诊断；原始记录与分析保留':d.source==='controller'?'后台监督记录':'执行宿主记录'}</p><details><summary>技术依据</summary><p>原因代码：{d.code}</p><TransportDetail observed={d.observed}/>{d.termination&&<p>终止方式：{d.termination}</p>}{d.detectedAt&&<p>记录时间：{d.detectedAt}</p>}{d.requestId&&<p>请求：{d.requestId}</p>}{d.observed&&<pre>{JSON.stringify(d.observed,null,2)}</pre>}{d.limits&&<pre>{JSON.stringify(d.limits,null,2)}</pre>}{d.evidence&&<p>归档依据：{d.evidence}</p>}{d.secondaryCodes?.length>0&&<p>后续清理或收集事件：{d.secondaryCodes.join('、')}</p>}</details></details>
}
