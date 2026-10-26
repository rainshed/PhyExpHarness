import React,{useState,useEffect,useRef} from 'react';
import {LibraryBrowser} from '../components/plugin-library';
import {libraryClient,libraryWrites} from '@phyexp/meta-workbench-client/plugin-library';
import {useResource} from '@phyexp/meta-workbench-client/react';
const client=libraryClient();
export function PluginLibraryPage(){
 const [writes]=useState(()=>libraryWrites(localStorage)),[jobId,setJobId]=useState(()=>localStorage.getItem('phyexp:plugin-library:job')||'');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);const job=useResource('library-job:'+jobId),active=useRef(true);
 useEffect(()=>{active.current=true;return()=>{active.current=false}},[]);
 useEffect(()=>{if(!jobId)return;let stopped=false,timer:any;
  const poll=async()=>{const result=await job.load(signal=>client.job(jobId,signal),{retain:true});if(stopped)return;if(['finished','failed'].includes(result.value?.state))setRefresh(v=>v+1);else timer=setTimeout(poll,2000)};
  poll();return()=>{stopped=true;clearTimeout(timer)};
 },[jobId]);
 const write=async(retry=false)=>{if(busy)return;setBusy(true);setError('');try{
  // Also publishes the current platform plugin without reviving deleted entries.
  if(!retry)await client.defaults();
  const result=retry?await writes.retry():await writes.send('/plugin-library/rescan',{});
  if(active.current){if(result?.jobId)setJobId(result.jobId);setRefresh(v=>v+1)}
 }catch(e:any){if(active.current)setError(e.message)}finally{if(active.current)setBusy(false)}};
 useEffect(()=>{client.defaults().then(()=>{if(active.current)setRefresh(v=>v+1)}).catch(e=>{if(active.current)setError(e.message)})},[]);
 return <section className="mh-card"><h1>插件库</h1><p>保存单个插件的源码版本，包括构建失败和未采用的版本。创建活动时，你可以选择多个插件组成 H0；Meta 只获得你选定的内容。</p>{error&&<p role="alert">{error}</p>}{job.error&&<p role="alert">{job.error}</p>}{job.value?.state==='running'&&<p role="status">历史插件导入中 · {job.value.cursor}/{job.value.candidateIds.length}</p>}{writes.pending()&&<button disabled={busy} onClick={()=>write(true)}>用原请求核对未确认操作</button>}
 <LibraryBrowser manage refresh={refresh} management={<><h4>从旧活动导入</h4><p>新活动的插件会自动入库。此操作用于找回启用插件库前，已保存在旧活动中的插件源码；不会重新运行实验，也不会恢复你已删除的版本。</p><button disabled={busy||!!writes.pending()} onClick={()=>write()}>从旧活动导入插件</button>{job.value&&<details open={job.value.state!=='finished'}><summary>历史导入 {job.value.state==='finished'?'完成':job.value.state==='failed'?'失败':'进行中'} · {job.value.cursor}/{job.value.candidateIds.length}</summary>{job.value.error&&<p role="alert">{job.value.error}。可重新导入，已保存内容不会重复。</p>}{job.value.results.map((r:any,i:number)=><p key={i}>{r.candidateId} · {r.error||`保存 ${r.plugins.length} 个插件`}{r.issues?.map((v:any)=>'；'+v.name+'：'+v.reason).join('')}</p>)}</details>}</>}/></section>;
}
