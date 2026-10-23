// H0 is persisted before reference images finish. It alone is not start readiness.
export function campaignPreparation(c={}) {
 const operations=(c.operations||[]).filter(o=>o.kind==='prepare_h0');
 const latest=operations.reduce((last,o)=>!last||(o.startedAt||0)>=(last.startedAt||0)?o:last,null);
 const h0=(c.candidates||[]).some(x=>!x.plugins.length&&x.check.status==='passed');
 const policy=c.references?.policy||c.referencePolicy||c.config?.referencePolicy||{};
 const harnesses=c.references?.bindings?.harnesses||c.config?.referenceBindings?.harnesses||{};
 const missing=policy.harnessEnabled?(policy.harnessRefs||[]).filter(id=>!harnesses[id]?.image):[];
 if(latest?.state==='failed')return {ready:false,label:'环境准备失败，请查看后台动态'};
 if(latest?.state==='running')return {ready:false,label:h0&&missing.length
  ?'正在准备参考 Harness：'+missing.map(id=>harnesses[id]?.name||id).join('、')+'…'
  :'正在准备环境与基线…'};
 if(!h0)return {ready:false,label:'正在准备环境与基线…'};
 if(missing.length)return {ready:false,label:'参考 Harness 尚未就绪，请查看后台动态'};
 return {ready:true,label:'启动进化'};
}
