import React from 'react';
export {API,api,key,defaults} from '@phyexp/meta-workbench-client';
export const states:any={draft:'待启动',running:'运行中',paused:'已暂停',closing:'正在收尾',finished:'已完成',failed:'失败',unknown:'待核实',reserved:'待执行',launching:'启动中',cancelled:'已取消',accepted:'已受理',waiting:'等待结果',completed:'已完成',interrupted:'已中断',recovering:'正在恢复',needs_attention:'需要处理'};
export const reasons:any={round_limit:'达到轮次上限',trial_limit:'达到实验次数上限',time_limit:'达到探索时间上限',token_threshold:'达到用量软阈值',campaign_deadline:'达到活动截止时间',trial_deadline:'达到单次时限',user_stop:'用户停止',meta_finished:'Meta 主动结束',meta_session_failed:'Meta 会话失败',startup_failure:'实验启动失败',supervisor_lost_start_not_repeated:'监督进程失联，未重复启动',completed:'执行完成'};
export const tasks:any={time_budgeted_hamlearn_10q:'10 比特 Hamiltonian 学习',time_budgeted_shadow_surrogate_60q:'60 比特 Shadow Surrogate',tunable_coupler_cz_netzero:'可调耦合器 CZ',logical_cnot_decoder_calibration:'逻辑 CNOT 解码器校准',adaptive_clustered_clbcs_h2o:'H₂O 自适应测量'};
export const short=(v:any)=>v?.slice(-8)||'—';export const number=(n:any)=>Number(n||0).toLocaleString('zh-CN');
export const duration=(n:any)=>{const s=Math.round(n||0);return `${Math.floor(s/3600)}小时 ${Math.floor(s%3600/60)}分 ${s%60}秒`;};
export const date=(n:any)=>n?new Date(n*1000).toLocaleString('zh-CN',{hour12:false}):'—';
export function Badge({value}:{value:string}){return <span className={'mh-badge '+value}>{states[value]||value}</span>;}
export function Text({value}:any){if(Array.isArray(value))return <ul>{value.map((v,i)=><li key={i}><Text value={v}/></li>)}</ul>;if(value&&typeof value==='object')return <dl>{Object.entries(value).map(([k,v])=><React.Fragment key={k}><dt>{k}</dt><dd><Text value={v}/></dd></React.Fragment>)}</dl>;return <span style={{whiteSpace:'pre-wrap'}}>{String(value??'—')}</span>;}
export function Metric({label,value,note}:any){return <div className="mh-metric"><small>{label}</small><strong>{value}</strong><span>{note}</span></div>}
