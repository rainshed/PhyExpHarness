import React,{useEffect,useRef} from 'react';
import {api,short,number} from './common';
import {LimitFields} from './fields';
import {evidenceEnd} from './evidence-text.mjs';
export function WorkbenchDialogs({w,evidenceIntro,allowEvidenceDownload=false}:any){
 const {busy,evidence,setEvidence,limits,setLimits,source,setSource,renaming,setRenaming,setNotice,limitsError,setLimitsError,act,saveLimits,closeDetails,readEvidence,readSource}=w;
 const host=useRef<HTMLDivElement>(null);
 const busyRef=useRef(busy);busyRef.current=busy;
 const open=!!(limits||evidence||source||renaming);
 async function downloadEvidence(){
  const id=evidence.id;
  await act('evidence',async()=>{
   const chunks:string[]=[];let offset=0,total:number|undefined;
   do{const page=await api('/evidence/'+id+'?offset='+offset+'&limit=16000');
    if(page.id!==id||page.offset!==offset||!Number.isSafeInteger(page.total)||page.total<0||(total!==undefined&&total!==page.total)||(typeof page.text!=='string'||(!page.text.length&&offset<page.total)||evidenceEnd(page)>page.total))throw Error('证据分页发生变化，请重新打开后下载。');
    total=page.total;chunks.push(page.text);offset=evidenceEnd(page);
   }while(offset<total!);
   const url=URL.createObjectURL(new Blob(chunks,{type:'text/plain;charset=utf-8'})),link=document.createElement('a');
   link.href=url;link.download=id+'.txt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
   setNotice('证据全文已准备下载。');
  });
 }
 useEffect(()=>{if(!open)return;const previous=((evidence||source)&&w.detailTrigger?.current)||document.activeElement as HTMLElement;const root=host.current;
  root?.querySelector<HTMLElement>('button,input,select,textarea')?.focus();
  const key=(event:KeyboardEvent)=>{if(event.key==='Escape'&&(!busyRef.current||['source','evidence'].includes(busyRef.current))){event.preventDefault();event.stopPropagation();setLimits(null);closeDetails();setRenaming(null)}
   if(event.key==='Tab'){const elements=Array.from(root?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea,a[href],summary')||[]).filter(e=>e.getClientRects().length);const first=elements[0],last=elements.at(-1);if(!root?.contains(document.activeElement)){event.preventDefault();first?.focus()}else if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}}};
  document.addEventListener('keydown',key);return()=>{document.removeEventListener('keydown',key);if(previous?.isConnected)previous.focus({preventScroll:true})};
 },[open]);
 return <div ref={host}> {limits&&<div className="mh-overlay"><section role="dialog" aria-modal="true" aria-label="调整活动上限" className="mh-dialog"><div className="mh-title"><h2>调整活动上限</h2><button onClick={()=>setLimits(null)}>关闭</button></div><p>只有用户可以调整。已消耗额度不清零；已经结束的活动不会恢复。已启动请求与实验保留原有时限。</p><form noValidate onSubmit={e=>{e.preventDefault();saveLimits()}}><LimitFields config={limits} onChange={(next:any)=>{setLimits(next);setLimitsError('')}}/><div role="alert">{limitsError&&<p className="mh-alert">{limitsError}</p>}</div><button className="primary" disabled={!!busy}>{busy==='limits'?'正在保存…':'保存上限'}</button></form></section></div>}
 {evidence&&<div className="mh-overlay"><section role="dialog" aria-modal="true" aria-label="证据阅读" className="mh-dialog wide"><div className="mh-title"><div><h2>归档依据 · {evidence.kind}</h2></div><button autoFocus onClick={closeDetails}>关闭证据</button></div>{evidenceIntro}<details><summary>完整身份与定位</summary><small>{evidence.id}</small><p>实验 {evidence.trialId}</p></details><p className="mh-muted">内容已校验 · {evidence.offset}–{Math.min(evidence.total,evidenceEnd(evidence))} / {number(evidence.total)} 字符</p><pre>{evidence.text}</pre><div className="mh-actions"><button disabled={!!busy||!evidence.offset} onClick={()=>readEvidence(evidence.id,Math.max(0,evidence.offset-16000))}>上一页</button><button disabled={!!busy||evidenceEnd(evidence)>=evidence.total} onClick={()=>readEvidence(evidence.id,evidenceEnd(evidence))}>下一页</button>{allowEvidenceDownload&&<button disabled={!!busy} onClick={downloadEvidence}>下载证据全文</button>}</div></section></div>}
 {source&&<div className="mh-overlay"><section role="dialog" aria-modal="true" aria-label="插件代码" className="mh-dialog wide"><div className="mh-title"><div><h2>{source.plugin.displayName} · {source.plugin.version}</h2><small>实验使用的冻结版本 · 只读预览</small></div><button autoFocus onClick={closeDetails}>关闭代码</button></div><div className="mh-actions"><button disabled={!!busy} onClick={()=>act('open-source',()=>api('/candidates/'+source.candidateId+'/plugins/'+source.plugin.id+'/open',{}))}>打开所在文件夹 ↗</button><button onClick={()=>act('copy-path',async()=>{await navigator.clipboard.writeText(source.directory);setNotice('插件目录路径已复制。')})}>复制路径</button></div><p className="mh-muted">{source.directory}</p><label>文件<select disabled={!!busy} aria-label="插件文件" value={source.file||''} onChange={e=>readSource(source.plugin,e.target.value)}><option value="">选择文件…</option>{source.files.map((f:string)=><option key={f}>{f}</option>)}</select></label>{source.content?<pre>{source.content}</pre>:<p>选择文件查看源码；修改草稿不会改变此冻结版本。</p>}</section></div>}
 {renaming&&<div className="mh-overlay"><section role="dialog" aria-label="修改版本名称" aria-modal="true" className="mh-dialog"><h2>修改版本名称</h2><p>短编号保持 {renaming.label}，名称只改变展示，不改变执行内容。</p><label>有意义的名称<input autoFocus maxLength={80} value={renaming.name} onChange={e=>setRenaming({...renaming,name:e.target.value})}/></label><div className="mh-actions"><button disabled={!!busy||!renaming.name.trim()} onClick={()=>act('rename',async()=>{await api('/candidates/'+renaming.id+'/name',{name:renaming.name});setRenaming(null);setNotice('名称已更新；历史原件保留。')})}>保存名称</button><button onClick={()=>setRenaming(null)}>取消</button></div></section></div>}</div>;
}
