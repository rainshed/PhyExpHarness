import React from 'react';
import {tasks} from './common';
import {coverageLabel,outcomeNote} from './trial-status.mjs';
const rate=(value:any)=>typeof value==='number'?(value*100).toFixed(1)+'%':'无可计分结果';
export function TaskEvaluation({value:v,details=false,rows=[],campaign:c={}}:any){
 if(!v)return null;
 const t=v.total;
 return <div className="mh-task-evaluation"><p><strong>任务成功率（任务等权）：{coverageLabel(v)}</strong><br/><small>可计分覆盖 {v.coveredTasks}/{v.taskCount} 个任务；逐次通过 {t.passed}/{t.eligible}，按规则计 0：{t.derivedFailures} 次。</small></p>
 {v.macroSuccessRate==null&&v.coveredTasks<v.taskCount&&<p className="mh-coverage">缺少 {v.taskCount-v.coveredTasks} 个任务的可计分结果；不代表这些任务仍在运行，也不按零计入。</p>}
 {outcomeNote(t,rows,c)&&<p className="mh-muted">{outcomeNote(t,rows,c)}</p>}
 {t.unresolved>0&&<p>待归因按失败计的逐次保守成功率：{rate(t.conservativeSuccessRate)}</p>}
 {details&&<details><summary>逐任务结果与计分规则</summary><p>{v.description}</p><div className="mh-table-wrap"><table><thead><tr><th>任务</th><th>通过 / 计入次数</th><th>按规则计 0</th><th>进度与未计分原因</th></tr></thead><tbody>{Object.entries(v.byTask).map(([task,r]:[string,any])=><tr key={task}><td>{tasks[task]||task}</td><td>{r.eligible?`${r.passed}/${r.eligible} · ${rate(r.successRate)}`:r.attempts?'无可计分结果':'未测'}</td><td>{r.derivedFailures}</td><td>{outcomeNote(r,rows.filter((t:any)=>t.task===task),c)||'结果已归档'}</td></tr>)}</tbody></table></div><small>规则：{v.rule}；官方评分未改写。</small></details>}</div>;
}
