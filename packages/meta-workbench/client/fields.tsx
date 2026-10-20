import React,{useId,useState,useEffect} from 'react';
// No browser number-input wheel handling. Only text and explicit step buttons change values.
export function NumberField({label,value,onChange,note,optional=false,emptyLabel='不限制',suggested=1,decimal=false}:any){
 const id=useId(),parsed=Number(value),empty=value===null||value===undefined;
 const [draft,setDraft]=useState(value??'');
 useEffect(()=>{if(!Object.is(Number(draft),Number(value)))setDraft(value??'')},[value]);
 return <div className="mh-number-field"><label htmlFor={optional&&empty?id+'-mode':id}>{label}</label><div className="mh-number-control">{optional&&<select id={id+'-mode'} aria-label={label+'模式'} aria-describedby={note?id+'-note':undefined} value={empty?'auto':'custom'} onChange={e=>onChange(e.target.value==='auto'?null:String(suggested))}><option value="auto">{emptyLabel}</option><option value="custom">自行设置</option></select>}{(!optional||!empty)&&<div className="mh-number"><input id={id} aria-describedby={note?id+'-note':undefined} type="text" inputMode={decimal?'decimal':'numeric'} autoComplete="off" value={decimal?draft:(value??'')} onChange={e=>{if((decimal?/^\d*(\.\d*)?$/:/^\d*$/).test(e.target.value)){if(decimal)setDraft(e.target.value);onChange(e.target.value)}}}/><div className="mh-steppers"><button type="button" aria-label={'增加'+label} onClick={()=>onChange(String((Number.isFinite(parsed)?parsed:0)+(decimal?0.5:1)))}>▴</button><button type="button" aria-label={'减少'+label} disabled={parsed<=0} onClick={()=>onChange(String(Math.max(0,(Number.isFinite(parsed)?parsed:0)-(decimal?0.5:1))))}>▾</button></div></div>}</div>{note&&<small id={id+'-note'}>{note}</small>}</div>
}
export function LimitFields({config,onChange}:any){
 const planned=config.resourcePolicy==='meta-resource-planning-v1';
 const change=(key:string,value:any)=>onChange({...config,[key]:value});
 const field=(key:string,label:string,options:any={})=><NumberField key={key} label={label} value={config[key]} onChange={(v:any)=>change(key,v)} {...options}/>;
 return <div className="mh-limits">
  <section className="mh-limit-section" aria-label="时间与并发"><h3>时间与并发</h3><p className="mh-muted">设置活动可使用的时间和同时运行的实验数。{planned?'具体实验安排由 Meta 在这些上限内规划。':''}</p><div className="mh-grid">
   <NumberField label="总运行时间（小时）" decimal value={config.wallTimeSeconds===''?'':Number(config.wallTimeSeconds)/3600} onChange={(v:any)=>change('wallTimeSeconds',v===''?'':Math.round(Number(v)*3600))} note="从启动时计时，包含报告与收尾；暂停不冻结计时。"/>
   {field('concurrency','最高并发',{note:'例如 5 表示同时最多运行 5 个实验，不是总实验次数。'})}
  </div></section>
  <section className="mh-limit-section" aria-label="可选上限"><h3>可选上限</h3><p className="mh-muted">按需限制轮次、实验总数或模型用量；不限制时，仍受总运行时间约束。</p><div className="mh-grid">
   {field('maxRounds','最多轮次',{optional:true,suggested:8,note:'包含 H0 基线；一轮可以包含多个实验。'})}
   {field('maxTrials','最多实验次数',{optional:true,suggested:Math.max(12,config.tasks?.length||0),note:`当前 ${config.tasks?.length||0} 个任务的 H0 基线至少需要 ${config.tasks?.length||0} 次实验。`})}
   {field('softTokenLimit','总用量软阈值（token）',{optional:true,suggested:3000000,note:'两个模型合计；达到阈值后停止新增请求，已发出的请求仍可能产生用量。'})}
  </div></section>
  <details className="mh-limit-advanced"><summary>高级运行设置</summary><p className="mh-muted">{planned?'单次时限与收尾预留可交给 Meta；自行设置时，分别作为单次上限和最低收尾预留。':'以下设置用于单次实验及活动收尾。'}</p><div className="mh-grid">
   {field('trialTimeSeconds','单次时限（秒）',{optional:true,emptyLabel:planned?'由 Meta 分配':'自动',suggested:3600,note:planned?'留空由 Meta 为批次分配；填写则作为单次上限。':'自动：至多 1 小时，并受剩余探索时间约束。'})}
   {field('reserveSeconds','收尾预留（秒）',{optional:true,emptyLabel:planned?'由 Meta 规划':'自动',suggested:900,note:planned?'留空不扣固定预留；填写则作为用户最低收尾预留。':'自动预留总时长的 10%，最多 15 分钟。'})}
   {field('reserveTokens','收尾预留（token）',{optional:true,emptyLabel:planned?'由 Meta 规划':'自动',suggested:300000,note:'仅在设置总用量阈值时生效；包含在总量内。'})}
  </div><label>达到时间上限时<select value={config.stopMode} onChange={e=>change('stopMode',e.target.value)}><option value="strict">严格停止剩余工作</option><option value="drain">给已启动实验有限额外收尾时间</option></select></label>{config.stopMode==='drain'&&field('drainGraceSeconds','额外收尾时限（秒，最多 900）')}<p className="mh-muted">自动重试为 0。token 阈值是软停止阈值，未提供可靠的金额硬上限。</p></details>
  <div className="mh-limit-summary" aria-label="运行额度摘要"><strong>本次运行额度</strong><ul><li>最多 {Number(config.wallTimeSeconds)/3600||'—'} 小时</li><li>同时最多 {config.concurrency||'—'} 个实验</li><li>{config.maxRounds==null?'轮次不限':'最多 '+config.maxRounds+' 轮'}</li><li>{config.maxTrials==null?'实验次数不限':'最多 '+config.maxTrials+' 次实验'}</li><li>{config.softTokenLimit==null?'模型用量不限':'用量软阈值 '+Number(config.softTokenLimit).toLocaleString()+' token'}</li></ul><small>报告与收尾包含在总时限内{config.stopMode==='drain'?'；已启动实验另有 '+config.drainGraceSeconds+' 秒额外收尾时间':'。'}</small></div>
 </div>
}
