import {reportContext} from './components/trial-status.mjs';
// Presentation helpers consume backend assessments; they never re-score trials.
export const finite = x => typeof x === 'number' && Number.isFinite(x);
const stable = x => JSON.stringify(x && typeof x === 'object' ? Array.isArray(x) ? x.map(v => JSON.parse(stable(v))) : Object.fromEntries(Object.keys(x).sort().map(k => [k, JSON.parse(stable(x[k] ?? null))])) : x ?? null);
export const percent = x => finite(x) ? (x * 100).toFixed(1) + '%' : '—';
export function trialsFor(c, id, task) {
  const live = new Map((c.trials || []).map(t => [t.id, t]));
  const rows = c.tables ? (c.tables.rounds || []).flatMap(r => r.results.map(t => ({...t, candidateId:r.candidateId, ...live.get(t.id)}))) : c.trials || [];
  return [...new Map(rows.map(t => [t.id,t])).values()].filter(t => (!id || t.candidateId === id) && (!task || t.task === task));
}
export function comparison(c, id, reference) {
  const a = trialsFor(c, reference), b = trialsFor(c, id), reasons = new Set();
  let missing = false, different = false, shared = 0;
  for (const task of c.config?.tasks || []) {
    const left = a.filter(t => t.task === task), right = b.filter(t => t.task === task);
    if (!left.length || !right.length) continue;
    shared++;
    const rows = [...left,...right], proof = rows.every(t => t.comparisonContext?.runnerExecutionManifest);
    const signatures = rows.map(t => {
      const p = t.comparisonContext;
      const budget = t.effectiveConditions || p?.executionConditions;
      const limit = budget?.trialTimeSeconds ?? t.taskTimeLimitSeconds;
      const actual = budget?.actualTimeSeconds ?? (finite(t.deadline) && finite(t.startedAt) ? t.deadline-t.startedAt : null);
      if (!p?.taskSourcesDigest || !(proof ? p.runnerExecutionManifest : p?.runnerImageId) || !(p?.verifierImageId || p?.taskImageIds?.length) || !finite(limit)) missing = true;
      // Rounded receipt durations avoid false differences from sub-second launch timing.
      return {source:p?.taskSourcesDigest, runner:proof?p?.runnerExecutionManifest:p?.runnerImageId, verifier:p?.verifierImageId, images:p?.taskImageIds,
        limit, actual:finite(actual)?Math.round(actual):null, ceiling:budget?.frozenTrialCeilingSeconds};
    });
    for (const key of ['source','runner','verifier','images','limit','actual','ceiling']) {
      const known = signatures.map(s => s[key]).filter(v => v != null);
      if (new Set(known.map(stable)).size > 1) {different = true; reasons.add(['limit','actual','ceiling'].includes(key)?'实验时限或实际预算不同':'任务来源或环境身份不同');}
    }
  }
  if (!shared || missing) reasons.add('部分实验缺少完整的任务、环境或预算记录');
  const state = different ? 'different' : missing || !shared ? 'unknown' : 'same';
  return {state, label:state==='different'?'条件不同，仅供参考':state==='unknown'?'可比较性待确认':'已记录条件一致', reasons:[...reasons]};
}
export function defaultVersions(c) {
  const versions = c.tables?.versions || [], baseline = versions[0]?.id;
  const retained = c.comparisonCandidateId || c.retainedCandidateId || c.finalCandidateId || versions.find(v=>v.retained||v.final)?.id;
  return [baseline, retained, versions.at(-1)?.id].filter((id,i,all) => id && all.indexOf(id)===i);
}
export function comparisonTasks(c, versions, common=false) {
  const tasks = c.config?.tasks || [];
  return common ? tasks.filter(task=>versions.length && versions.every(v=>v.taskEvaluation?.byTask?.[task]?.eligible>0)) : tasks;
}
export function taskMean(v, tasks) {
  const rows = tasks.map(t=>v.taskEvaluation?.byTask?.[t]);
  return rows.length && rows.every(r=>r?.eligible>0 && finite(r.successRate)) ? rows.reduce((sum,r)=>sum+r.successRate,0)/rows.length : null;
}
export {outcomeNote} from './components/trial-status.mjs';
export function versionCost(rows) {
  const usage = rows.map(t=>t.accountedUsage || t.summary?.accounting); // Ledger snapshot or archived accounting receipt, never a guessed token total.
  const recorded = usage.filter(u=>finite(u?.confirmedTokens));
  const timed = rows.filter(t=>finite(t.startedAt)&&finite(t.finishedAt));
  return {tokens:recorded.length?recorded.reduce((n,u)=>n+u.confirmedTokens,0):null, recorded:recorded.length, attempts:rows.length,
    unknown:recorded.reduce((n,u)=>n+(u.unknownRequests||0),0), unknownReserved:recorded.reduce((n,u)=>n+(u.unknownReservedTokens||0),0), seconds:timed.length?timed.reduce((n,t)=>n+Math.max(0,t.finishedAt-t.startedAt),0):null, timed:timed.length};
}
export const reportKey = r => r.batchId || r.kind;
export function reportGroups(reports=[], batches=[]) {
  const groups = new Map();
  for (const r of reports) {const key=reportKey(r);groups.set(key,[...(groups.get(key)||[]),r]);}
  return [...groups.values()].map(rows=>rows.sort((a,b)=>(b.analysisRevision||0)-(a.analysisRevision||0)||(b.createdAt||0)-(a.createdAt||0))).sort((a,b)=>{
    if (!!a[0].batchId !== !!b[0].batchId) return a[0].batchId?1:-1;
    return (batches.find(r=>r.id===b[0].batchId)?.round||0)-(batches.find(r=>r.id===a[0].batchId)?.round||0)||(b[0].createdAt||0)-(a[0].createdAt||0);
  });
}
export function reportTitle(r, batches=[]) {return r.kind==='status_summary'||r.status==='analysis_incomplete'?'阶段摘要 · 分析未完成':r.kind==='final'?'最终研究报告':`第 ${batches.find(b=>b.id===r.batchId)?.round ?? '—'} 轮报告`;}
export function reportCampaign(report) {
  return {...reportContext(report), comparisonCandidateId:report.batchId?report.tables?.rounds.find(r=>r.id===report.batchId)?.candidateId:null};
}

export function trialBucket(t) {
  if (['running','launching'].includes(t.state)) return 'active';
  if (['reserved','queued'].includes(t.state)) return 'queued';
  if (t.state==='unknown' && !t.finishedAt) return 'unknown';
  return 'ended';
}
export function trialLabel(c,t) {
  const r=c.tables?.rounds?.find(r=>r.id===t.batchId||r.results?.some(x=>x.id===t.id));
  const index=r?.results?.findIndex(x=>x.id===t.id);
  return r && index>=0 ? `第 ${r.round} 轮 · 实验 ${index+1}` : `实验 ${t.id}`;
}
export function trialReport(c,t) {
  const batch=t.batchId||c.tables?.rounds?.find(r=>r.results?.some(x=>x.id===t.id))?.id;
  return reportGroups(c.reports||[]).find(rows=>batch&&rows[0].batchId===batch)?.[0]?.id;
}
