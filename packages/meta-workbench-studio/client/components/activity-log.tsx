import React from 'react';
import {Badge,short,date,reasons} from './common';
import {metaFailureReason} from './campaign-status.mjs';
export function ActivityLog({w}:any){const {c,events}=w;const latest=c.metaSessions.at(-1);return <section className="mh-card" data-reading-anchor="meta-status" tabIndex={-1}>
 <h3>后台动态与会话</h3>
 {c.operations.map((o:any)=><p key={o.id}><Badge value={o.state}/> {o.kind==='prepare_h0'?'准备任务环境、基线与参考 Harness':o.kind==='export_relocation'?'导出包独立装配检查':'候选装配检查'} {o.error&&<span className="mh-error">{o.error}</span>}</p>)}
 {latest?.state==='waiting'&&<p>Meta 正在等待实验或后台操作完成；在途 {c.counts.activeTrials} 次，待执行 {c.counts.reservedTrials} 次。单次结束后通知 Meta。</p>}
 {c.metaSessions.slice().reverse().map((s:any)=><div key={s.id}>
  <p><Badge value={s.state}/> {s===latest?'当前':'历史'} Meta 会话 {short(s.id)} · {date(s.startedAt)}</p>
  {(s.recovery?.failure||s.summary?.failure||s.summary?.error)&&<><p>{metaFailureReason(s)}{s.recovery?.reason==='recovery_exhausted'?'；自动恢复次数已用完。':'。'}</p>
   <details><summary>技术详情与原始错误</summary><p>会话：{s.id}</p>{(s.recovery?.failure||s.summary?.failure)?.code&&<p>故障代码：{(s.recovery?.failure||s.summary?.failure).code}</p>}{s.summary?.error&&<pre>{s.summary.error}</pre>}</details></>}
 </div>)}
 <details><summary>事件记录（最近 {events.length} 条）</summary><ol>{events.slice().reverse().map((e:any)=><li key={e.seq}>{date(e.time)} · {e.type}{e.reason&&' · '+(reasons[e.reason]||e.reason)}{e.round&&' · 第 '+e.round+' 轮'}</li>)}</ol></details>
 </section>}
