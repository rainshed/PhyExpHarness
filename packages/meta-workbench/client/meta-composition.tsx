import React from 'react';
import {MetaQuestions} from './meta-questions';
const names:any={'meta-control':'后台服务','meta-campaign':'活动管理','meta-experiments':'实验与版本','meta-evidence':'完整材料','meta-reporting':'报告与导出','meta-stop-review':'独立停止审查',control:'活动服务',context:'活动上下文',queries:'只读查询',actions:'实验操作','stop-review':'停止审查','review-context':'审查上下文','review-queries':'审查查询'};
const states:any={pending:'审查中',approved:'批准停止',consumed:'已批准并结束探索',continue:'继续探索',insufficient_evidence:'证据不足',failed:'审查未完成，未批准'};
export function MetaComposition({campaign,composition,observations=[],sessions=[],reviews=[]}:any){
 const value=composition||campaign?.config?.metaComposition;
 if(!value)return <p className="mh-muted">此历史活动沿用原 Meta 规则，未补写插件组合或停止审查记录。</p>;
 const loaded=new Set(sessions.flatMap((s:any)=>Object.values(s.agents||{}).flatMap((a:any)=>(a.plugins||[]).flatMap((p:any)=>(p.modules||[]).map((m:any)=>a.preset+'/'+m.moduleName.split('/').at(-1))))));
 return <section className="mh-card"><h3>Meta 插件组合与停止审查</h3><p>组合：{value.preset} · {value.id.slice(0,12)}。插件内容、配置与依赖引用已冻结，运行环境按版本重建。</p>
 <MetaQuestions rows={campaign?.metaQuestions}/>
 {sessions.at(-1)?.state==='needs_attention'&&<p className="mh-error">Meta 自动恢复已停止，活动历史与已受理实验保留。请查看会话中断原因，处理后暂停并恢复活动。</p>}
 {sessions.at(-1)?.state==='recovering'&&<p>Meta 正在恢复原生会话；不会重新提交已受理的实验。</p>}
 <details><summary>查看插件加载与触发情况</summary><ul>{value.plugins.map((p:any)=>{const hits=observations.filter((o:any)=>o.pluginId===p.id&&o.event==='triggered');const mounted=p.roles?(p.id==='meta-control'?sessions.some((s:any)=>Object.keys(s.agents||{}).length):p.roles.some((role:string)=>loaded.has(({meta:'phyexp-meta',research:'phyexp-researcher',reviewer:'phyexp-stop-reviewer'} as any)[role]+'/'+p.module))):p.scope==='host'?sessions.some((s:any)=>Object.keys(s.agents||{}).length):loaded.has((p.scope==='meta'?'phyexp-meta':'phyexp-stop-reviewer')+'/'+p.module);return <li key={p.id}>{names[p.id]||p.id}：{!p.enabled?'已禁用':hits.length?'已触发 '+hits.length+' 次':mounted?(['queries','actions','stop-review','review-queries'].includes(p.id)?'已加载，尚未触发':'已加载，未单独观测触发'):'尚无加载回执'}。</li>})}</ul><p className="mh-muted">触发次数不能证明插件有效；审查用量属于 Meta 总用量，不重复相加。未运行的审查会话不会显示为已加载。</p><small>完整组合标识：{value.id}</small></details>
 {reviews.length?reviews.map((r:any)=><div key={r.id}><h4>{states[r.state]||r.state}</h4><p>{r.result?.reason||r.failure||r.request?.reason}</p>{r.result?.nextDirections?.length>0&&<p>建议继续：{r.result.nextDirections.join('；')}</p>}{r.result?.missingEvidence?.length>0&&<p>尚缺证据：{r.result.missingEvidence.join('；')}</p>}<small>审查 {r.id.slice(-8)} · {r.usage?Number(r.usage.confirmedTokens).toLocaleString('zh-CN')+' token（已计入 Meta）':'用量尚未完成归集'}</small></div>):<p>尚未申请提前停止。普通对话轮次结束会继续推进活动；资源上限和用户停止由后台直接处理。</p>}
 {campaign?.finishAssessment&&<p>最终停止依据：{campaign.finishAssessment.reason}</p>}
 </section>;
}
