// Read-only presentation. Pending assessments are not evidence of active grading.
const finite = n => typeof n === 'number' && Number.isFinite(n);
export const isPending = t => ['reserved','queued','launching','running','collecting'].includes(t.state);
export function trialStage(t) {
  if (['reserved','queued'].includes(t.state)) return {key:'queued',label:'排队'};
  if (t.state === 'collecting') return {key:'collecting',label:'结果归集中'};
  if (t.state === 'launching') return {key:'launching',label:'启动中'};
  if (t.state === 'running') {
    // Optional explicit phase receipts only; the current controller does not emit these.
    if (['verifier','grading','scoring'].includes(t.phase) || t.scoringStatus === 'running')
      return {key:'scoring',label:'评分中'};
    if (t.phase === 'execution') return {key:'running',label:'运行中'};
    if (t.phase === 'collection') return {key:'collecting',label:'结果归集中'};
    return {key:'running',label:'运行中 · 阶段未细分'};
  }
  return {key:'terminal',label:t.completionLabel || t.resultLabel ||
    (finite(t.score) ? '评分 '+t.score : ({failed:'失败 · 未评分',cancelled:'已取消',completed:'已结束 · 未评分',finished:'已结束 · 未评分'}[t.state] || '状态未记录'))};
}
export function contextTrials(c={}) {
  const rows = new Map((c.tables?.rounds || []).flatMap(r =>
    (r.results || []).map(t => [t.id,{...t,candidateId:r.candidateId,batchId:r.id}])));
  for (const t of c.trials || []) rows.set(t.id,{...rows.get(t.id),...t});
  return [...rows.values()];
}
export function waitingReason(t,c={}) {
  if (trialStage(t).key !== 'queued') return null;
  if (c.state === 'paused') return '活动已暂停，等待恢复后调度';
  if (c.state === 'draft') return '活动尚未启动';
  if (['closing','finished','failed'].includes(c.state)) return '活动已收尾或结束，不再启动新实验';
  if(t.scheduling?.lateStartAllowed&&t.scheduling.state==='currently_infeasible')return t.scheduling.reason==='campaign_deadline'?'活动已到截止时间，不再启动新实验':'剩余时间已进入收尾预留，等待调整计划';
  if (t.scheduling?.state === 'currently_infeasible' || t.conditionsRequired?.canShorten === false) return `当前剩余时间无法容纳完整任务（需要 ${Math.ceil(t.scheduling?.requiredSeconds??t.conditionsRequired?.requiredSeconds??0)} 秒，可用 ${Math.floor(t.scheduling?.availableSeconds??t.conditionsRequired?.availableSeconds??0)} 秒）；可撤回未启动项或调整活动截止时间` ;
  if (t.conditionsRequired) return '剩余可用时长不足，等待确认缩短本次实验或调整计划';
  if (c.config?.resourcePolicy === 'meta-resource-planning-v1' && !c.resourcePlanning?.plan)
    return '等待 Meta 提交运行计划';
  const active = c.counts?.activeTrials ?? contextTrials(c).filter(t => ['running','launching'].includes(t.state)).length;
  const limit = c.resourcePlanning?.effectiveParallelism ?? c.config?.concurrency;
  if (finite(limit) && limit > 0 && active >= limit) return `并发名额已满（${active}/${limit}），等待在途实验结束`;
  const reason = c.resourcePlanning?.schedulingWait?.reason;
  if (reason === 'closeout_time') return '剩余时间已进入收尾预留，等待调整计划';
  if (reason === 'token_capacity') return '可用 token 额度不足，等待用量结算或调整计划';
  if(t.scheduling?.lateStartAllowed&&t.scheduling.interruptionRisk)return `等待后台调度；当前可用 ${Math.floor(t.scheduling.availableSeconds)} 秒，允许启动但可能受活动截止中断`;
  return c.historical ? '快照未记录具体等待原因' : '等待后台调度，未记录进一步原因';
}
export function trialTiming(t,c={},now=Date.now()/1000) {
  const queued = trialStage(t).key === 'queued';
  const start = queued ? (c.batches || []).find(b => b.id === t.batchId)?.acceptedAt : t.startedAt;
  const end = finite(t.finishedAt) ? t.finishedAt : c.historical ? c.snapshotAt : now;
  // An old terminal record without an end time must not acquire a growing duration.
  const seconds = finite(start) && finite(end) && (isPending(t) || finite(t.finishedAt))
    ? Math.max(0,end-start) : null;
  return {start:finite(start)?start:null,seconds,
    label:queued?(c.historical?'当时已排队':'已排队'):finite(t.finishedAt)?'总耗时':c.historical?'当时已运行':'已运行'};
}
export function pendingSummary(total,rows=[],historical=false) {
  if (!total) return '';
  const active = [...new Map(rows.filter(isPending).map(t => [t.id,t])).values()];
  if (active.length > total) return `尚无结果 ${total}（阶段未记录）`;
  const counts = new Map();
  for (const t of active) {const label=trialStage(t).label.replace(' · 阶段未细分','（阶段未细分）');counts.set(label,(counts.get(label)||0)+1);}
  if (active.length < total) counts.set('阶段未记录',total-active.length);
  return (historical?'当时：':'')+[...counts].map(([k,n])=>`${k} ${n}`).join(' · ');
}
export function outcomeNote(r,rows=[],c={}) {
  if (!r?.attempts) return '未测';
  return [
    ...[['external_failure','未计分故障'],['not_started','未执行'],['cancelled','取消'],['unresolved',c.config?.taskEvaluationRule==='task-completion-v4'?'结束状态待核实':'待归因']]
      .filter(([k])=>r[k]>0).map(([k,label])=>`${label} ${r[k]}`),
    pendingSummary(r.pending,rows,c.historical)
  ].filter(Boolean).join(' · ') || (r.eligible ? '' : '无可计分结果');
}
export function coverageLabel(v) {
  if (finite(v?.macroSuccessRate)) return (v.macroSuccessRate*100).toFixed(1)+'%';
  return v?.taskCount>0 && v.coveredTasks<v.taskCount ? '覆盖不足，暂不计算' : '暂无可计分结果';
}
export function activityProgress(c) {
  const rows=contextTrials(c),n=rows.filter(isPending).length;
  return pendingSummary(n,rows,c.historical) || '无排队或在途实验';
}
export function reportContext(report) {
  const f=report.facts,c=f.campaign;
  // A readability revision may be created days later than its immutable facts.
  // Live activity elapsedSeconds was captured with those facts. Never use now.
  const snapshotAt = finite(c.startedAt) && finite(c.elapsedSeconds) && ['running','paused','closing'].includes(c.state)
    ? c.startedAt+c.elapsedSeconds
    : !report.presentationSourceReportId && finite(report.createdAt) ? report.createdAt : null;
  return {...c,...Object.fromEntries(['batches','trials','candidates','evidence','selectionDecisions','metaSessions','metaObservations','stopReviews'].map(k=>[k,f[k]||[]])),
    tables:report.tables,historical:true,snapshotAt};
}
