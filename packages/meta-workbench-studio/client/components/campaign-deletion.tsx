import React,{useEffect,useRef} from 'react';

export function DeletionProgress({w}:any){
 const {c,busy,connected}=w,job=c.deletion,failed=job.state==='failed';
 return <section className="mh-empty" aria-label="活动删除进度" aria-live="polite">
  <h1>{failed?'删除尚未完成':job.phase==='stopping'?'正在停止所属工作':'正在清理活动数据'}</h1>
  <p><strong>{c.config.name||c.id}</strong></p>
  <p>{job.phase==='stopping'?'后台正在停止 Meta、子会话和实验，并等待构建与导出退出。':'后台正在删除会话、实验、证据、报告和导出，并回收没有其他引用的内容。'}</p>
  {failed?<><p className="mh-alert" role="alert">{job.error}</p><button className="studio-danger" disabled={!!busy||!connected} onClick={()=>w.deleteCampaign(true)}>{busy==='retry-delete'?'正在提交…':'重试删除'}</button></>:<p>关闭页面后仍会继续；再次打开可查看进度。</p>}
  <p>清理完成前活动保持可见，不能恢复运行。</p>
 </section>;
}

export function DeletionDialog({w}:any){
 const host=useRef<HTMLElement>(null),busy=useRef(w.busy);busy.current=w.busy;
 useEffect(()=>{
  if(!w.deleteOpen)return;
  const previous=document.activeElement as HTMLElement,root=host.current;
  root?.querySelector<HTMLElement>('button')?.focus();
  const key=(e:KeyboardEvent)=>{
   if(e.key==='Escape'&&!busy.current){e.preventDefault();w.closeDeletion()}
   if(e.key==='Tab'){
    const items=Array.from(root?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href]')||[]),first=items[0],last=items.at(-1);
    if(!root?.contains(document.activeElement)||e.shiftKey&&document.activeElement===first){e.preventDefault();(e.shiftKey?last:first)?.focus()}
    else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}
   }
  };
  document.addEventListener('keydown',key);
  return()=>{document.removeEventListener('keydown',key);if(previous?.isConnected)previous.focus()};
 },[w.deleteOpen]);
 if(!w.deleteOpen)return null;
 const {value:preview,loading,error}=w.deletion,counts=preview?.counts||{},blockers=preview?.blockers||[];
 return <div className="mh-overlay"><section ref={host} className="mh-dialog" role="dialog" aria-modal="true" aria-labelledby="campaign-delete-title">
  <div className="mh-title"><h2 id="campaign-delete-title">永久删除活动</h2><button disabled={!!w.busy} onClick={w.closeDeletion}>取消</button></div>
  <p><strong>{preview?.name||w.c?.config.name||w.selected}</strong></p>
  {loading?<><p role="status">正在核对删除范围与引用…</p><p>历史较多时需要一些时间。核对最多等待两分钟，期间可以取消；此时尚未提交删除。</p></>:error?<p className="mh-alert" role="alert">{error}</p>:preview&&<>
   <p>将删除 {(counts.trials||0)+(counts.reference_runs||0)} 次实验、{counts.candidates||0} 个候选、{counts.reports||0} 份报告修订、{counts.exports||0} 份导出，以及全部会话、轨迹、用量和研究记录。</p>
   <p>此操作无法撤销。其他活动仍在使用的共享内容会保留。已经另行下载或复制的文件不随之删除。</p>
   {blockers.length>0&&<div className="mh-alert" role="alert"><p>以下依赖尚未处理，不能删除：</p><ul>{blockers.map((item:any,i:number)=><li key={i}>{item.message}</li>)}</ul></div>}
   {w.error&&<p className="mh-alert" role="alert">{w.error}</p>}
   <button className="studio-danger" disabled={!!w.busy||!w.connected||!!blockers.length||preview.state!=='preview'} onClick={()=>w.deleteCampaign()}>{w.busy==='delete'?'正在提交…':preview.requiresStop?'停止并永久删除':'永久删除'}</button>
  </>}
  {(error||w.error)&&<button disabled={!!w.busy||loading} onClick={w.openDeletion}>重新核对</button>}
 </section></div>;
}
