import {number,tasks} from '../components/common';
import {FailureDetail} from '../components/failure';
import {TrialStatus} from '../components/trial-status';
import {versionCost} from '../readability.mjs';


export function TrialList({rows,campaign={},onEvidence,onStopTrial}:any){return <div className="studio-trials">{!rows.length&&<p className="mh-muted">此范围尚无实验记录。</p>}{rows.map((t:any,i:number)=><section className="studio-trial" key={t.id}><div className="mh-title"><strong>{tasks[t.task]||t.task} · 实验 {i+1}</strong></div><TrialStatus trial={t} campaign={campaign}/><p className="mh-muted">{versionCost([t]).tokens==null?'确认用量尚未归档':number(versionCost([t]).tokens)+' token 已确认'}{versionCost([t]).unknownReserved?' · 另有未知用量预留':''}</p><FailureDetail trial={t}/><div className="mh-actions"><button onClick={()=>onEvidence(t.id)}>查看本次依据</button>{!campaign.historical&&onStopTrial&&['running','launching'].includes(t.state)&&<button onClick={()=>onStopTrial(t.id)}>终止本次实验</button>}</div><details><summary>完整实验身份与计分依据</summary><p>{t.id}</p><pre>{JSON.stringify({state:t.state,officialScore:t.score,assessment:t.taskAssessment,conditions:t.effectiveConditions||t.comparisonContext},null,2)}</pre></details></section>)}</div>}
