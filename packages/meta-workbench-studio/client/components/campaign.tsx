import React from 'react';
import {StorageNotice} from './storage';
import {number,duration,date,reasons,tasks} from './common';
import {campaignStatus} from './campaign-status.mjs';
import {campaignPreparation} from './campaign-preparation.mjs';
export function CampaignActions({w}:any){const {c,busy,connected,command,setLimits,setLimitsError,finalReport,readReport}=w;
 const preparation=campaignPreparation(c);
 return <div className="mh-actions studio-actions">
  {c.state==='draft'&&<button className="primary" disabled={!!busy||!connected||!preparation.ready} onClick={()=>command('start')}>{busy==='start'?'正在检查并启动…':preparation.label}</button>}
  {['running','closing'].includes(c.state)&&<button disabled={!!busy||!connected} onClick={()=>command('pause')}>{c.state==='closing'?'Ⅱ 暂停收尾':'Ⅱ 暂停新工作'}</button>}
  {c.state==='paused'&&<button className="primary" disabled={!!busy||!connected} onClick={()=>command('resume')}>{busy==='resume'?'正在检查并恢复…':'恢复活动'}</button>}
  {!['finished','failed'].includes(c.state)&&<button disabled={!!busy||!connected} onClick={()=>{setLimits({...c.config});setLimitsError('')}}>调整上限</button>}
  {['running','paused','closing'].includes(c.state)&&<button className="studio-danger" disabled={!!busy||!connected} onClick={()=>command('stop')}>停止并收尾</button>}
  {finalReport&&<button onClick={()=>readReport(finalReport.id)}>{finalReport.kind==='status_summary'?'阅读阶段摘要 ↗':'阅读总报告 ↗'}</button>}
  <details><summary>更多操作</summary><button className="studio-danger" disabled={!!busy||!connected} onClick={w.openDeletion}>删除活动…</button></details>
 </div>;
}

export function CampaignNotices({c,onDetails,onResume,busy='',connected=true}:any){const status=campaignStatus(c);return <>
 {status.attention&&<section className="studio-attention" role="alert" aria-label="活动需要处理">
  <h3>需要处理 · Meta 已停止推进</h3>
  <p><strong>{status.reason}。</strong>{status.recoveryNote}</p>
  <p>{c.counts?.activeTrials?`已启动的 ${c.counts.activeTrials} 次实验仍由后台继续执行；Meta 暂时无法分析结果和安排后续研究。`:'当前没有正在执行的实验；后续研究需恢复 Meta 才能继续。'}{c.counts?.reservedTrials>0&&`另有 ${c.counts.reservedTrials} 次已受理实验等待后台调度。`}</p>
  <p>{c.remainingSeconds===0?'活动已到截止时间，无法恢复。':'处理原因后，点击“恢复活动”即可继续。墙钟仍在计时。'}</p>
  <div className="mh-actions">
   {onResume&&<button className="primary" disabled={!!busy||!connected||c.remainingSeconds===0} onClick={onResume}>{busy==='resume'?'正在提交恢复…':'恢复活动'}</button>}
   {onDetails&&<button onClick={onDetails}>查看中断详情 →</button>}
  </div>
 </section>}
 {c.storage&&<StorageNotice storage={c.storage} connected={connected}/>}
 {status.recovering&&<section className="mh-notice" role="status" aria-label="Meta 正在恢复"><strong>{status.manualRecovery?'Meta 正在恢复':'Meta 正在自动恢复'}</strong><p>{status.manualRecovery?'恢复请求已受理，后台正在接续 Meta 会话。':status.reason+'。后台正在尝试接续会话。'}已受理实验仍由后台监督。</p></section>}
 {c.state==='paused'&&<p className="mh-notice">已暂停新工作，已启动实验继续；Meta 当前请求中断。墙钟仍在计时，恢复时先对账。</p>}
 {c.state==='closing'&&!status.attention&&!status.recovering&&<p className="mh-notice">正在收尾，等待外部任务终止确认、用量归集和报告。操作受理不代表任务已经停止。</p>}
 {c.stopReason&&<p className={c.state==='finished'?'studio-ended-reason':'mh-notice'}>{c.explorationClosed&&c.state==='running'?'探索已关闭，已受理实验继续；原因：':'停止原因：'}{reasons[c.stopReason]||c.stopReason}</p>}
 {c.config.precedingAttempt&&<p className="mh-notice">前序失败已保留：{c.config.precedingAttempt.trials} 次尝试，已确认 {number(c.config.precedingAttempt.confirmedTokens)} token，未知预留 {number(c.config.precedingAttempt.unknownReservedTokens)} token。此活动使用原总额度的剩余部分。</p>}
 </>}

export function CampaignDetails({c}:any){return <details className="studio-config"><summary>活动目标、固定配置与请求保护</summary><p>{c.config.objective}</p><p>版本选择规则：{c.retentionRuleDescription||'历史活动沿用创建时规则。'}</p><div className="mh-grid"><div><h4>开发任务</h4><ul>{c.config.tasks.map((t:string)=><li key={t}>{tasks[t]||t}</li>)}</ul></div><div><h4>运行上限</h4><p>总时间 {duration(c.config.wallTimeSeconds)} · 并发 {c.config.concurrency}<br/>最多轮次 {c.config.maxRounds??'不限制'} · 最多实验 {c.config.maxTrials??'不限制'}<br/>单次时限 {c.config.executionTimePolicy?.version==='benchmark-time-v1'?'遵循各题 benchmark':c.config.trialTimeSeconds==null?(c.config.resourcePolicy?'由 Meta 分配':'自动'):duration(c.config.trialTimeSeconds)}<br/>收尾时间 {c.config.reserveSeconds==null?'自动':duration(c.config.reserveSeconds)} · 收尾用量 {c.config.reserveTokens==null?'自动':number(c.config.reserveTokens)+' token'}<br/>停止模式 {c.config.stopMode==='drain'?'有限排空，额外 '+duration(c.config.drainGraceSeconds):'严格停止'}</p></div></div>{c.executionProtection&&<>{c.executionProtection.version==='benchmark-stream-v1'?<p>模型请求与工具执行遵循 benchmark 求解截止时间。</p>:<p>单请求最长 {c.executionProtection.requestTimeoutMs/60000} 分钟；连续 {c.executionProtection.streamIdleTimeoutMs/1000} 秒无数据即终止，包含等待首次响应。</p>}<p>单响应上限 {c.executionProtection.maxResponseBytes/1024} KiB；工具参数 {c.executionProtection.maxToolArgumentBytes/1024} KiB。持续空白和确定无效参数会终止执行，不自动重试。本地限制不保证费用硬上限。</p></>}</details>}
