import React from 'react';
const rate=(value:any)=>typeof value==='number'?(value*100).toFixed(1)+'%':'待定';
export function TaskEvaluation({value:v,details=false}:any){
 if(!v)return null;
 const t=v.total;
 return <div className="mh-task-evaluation"><p><strong>任务成功率（任务等权）：{rate(v.macroSuccessRate)}</strong><br/><small>覆盖 {v.coveredTasks}/{v.taskCount} 个任务；逐次通过 {t.passed}/{t.eligible}，按规则计 0：{t.derivedFailures} 次。</small></p><p className="mh-muted">未计分外部故障 {t.external_failure} · 取消 {t.cancelled} · 待定 {t.pending} · 待归因 {t.unresolved}</p>{t.unresolved>0&&<p>待归因按失败计的逐次保守成功率：{rate(t.conservativeSuccessRate)}</p>}{details&&<details><summary>逐任务结果与计分规则</summary><p>{v.description}</p><div className="mh-table-wrap"><table><thead><tr><th>任务</th><th>通过 / 计入次数</th><th>按规则计 0</th><th>未计分故障 / 取消 / 待定 / 待归因</th></tr></thead><tbody>{Object.entries(v.byTask).map(([task,r]:[string,any])=><tr key={task}><td>{task}</td><td>{r.passed}/{r.eligible} · {rate(r.successRate)}</td><td>{r.derivedFailures}</td><td>{r.external_failure} / {r.cancelled} / {r.pending} / {r.unresolved}</td></tr>)}</tbody></table></div><small>规则：{v.rule}；官方评分未改写。</small></details>}</div>;
}
