import React,{useState} from 'react';
import {api} from '@phyexp/meta-workbench-client';
import {duration} from './common';

const GiB=1024**3;
const fields=[['maxDataBytes','全部活动数据上限'],['maxCampaignBytes','每个活动上限'],['minFreeBytes','最低磁盘剩余'],['criticalFreeBytes','紧急停止水位']];
export function StorageNotice({storage:s,connected}:any){
 const [draft,setDraft]=useState<any>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 async function load(){setBusy(true);setMessage('');try{const value=await api('/storage');setDraft(Object.fromEntries(fields.map(([key])=>[key,value.policy[key]/GiB])))}catch(e:any){setMessage(e.message)}finally{setBusy(false)}}
 async function save(e:React.FormEvent){e.preventDefault();setBusy(true);setMessage('');try{await api('/storage/policy',Object.fromEntries(fields.map(([key])=>[key,Math.round(Number(draft[key])*GiB)])));setMessage('存储上限已保存，下一次后台检查生效。')}catch(e:any){setMessage(e.message)}finally{setBusy(false)}}
 return <section className="mh-notice" aria-label="活动存储">
  <strong>{s.waiting?'等待存储空间':'活动存储'}</strong>
  <p>本活动 {(s.campaignBytes/GiB).toFixed(2)} / {(s.maxCampaignBytes/GiB).toFixed(1)} GiB · 全部数据 {(s.dataBytes/GiB).toFixed(2)} / {(s.maxDataBytes/GiB).toFixed(1)} GiB · 磁盘剩余 {Math.min(...s.disks.map((d:any)=>d.free/GiB)).toFixed(1)} GiB</p>
  {s.archive?.enabled&&<p>NFS 归档 {(s.archive.storedBytes/GiB).toFixed(2)} GiB · {s.archive.objectCount} 个对象 · {({idle:'等待巡检',running:'正在归档',complete:'本轮完成',retry:'等待重试',delayed:'归档响应较慢'} as any)[s.archive.state]||s.archive.state}。活动中已发布的证据保留在本地。</p>}
  {s.archive?.error&&<p role="status">归档暂未完成：{s.archive.error}。本轮未验证的文件保留在本地。</p>}
  {s.waiting&&<p role="status">{s.reasons.join('；')}。后台暂停新工作，空间恢复后继续；墙钟仍在计时。</p>}
  <details><summary>容量趋势与存储上限</summary>
   <p>{s.growthBytesPerSecond==null?'正在积累增长统计；至少观察一小时后提供估计。':`近期净增长 ${(s.growthBytesPerSecond*86400/GiB).toFixed(2)} GiB/天。`}{s.estimatedSecondsRemaining!=null&&` 按当前增长速度预计剩余 ${duration(s.estimatedSecondsRemaining)}，不是容量保证。`}</p>
   <p>上限对本机所有采用存储保护的新活动生效。提高上限不会增加实际磁盘容量。</p>
   {!draft?<button disabled={!connected||busy} onClick={load}>{busy?'读取中…':'调整存储上限'}</button>:<form onSubmit={save}>
    {fields.map(([key,label])=><label key={key}>{label}（GiB）<input type="number" min="0.1" step="0.1" required value={draft[key]} disabled={busy} onChange={e=>setDraft({...draft,[key]:e.target.value})}/></label>)}
    <div className="mh-actions"><button type="submit" disabled={!connected||busy}>{busy?'保存中…':'保存上限'}</button><button type="button" disabled={busy} onClick={()=>{setDraft(null);setMessage('')}}>取消</button></div>
   </form>}
   {message&&<p role="status">{message}</p>}
   {s.errors?.length>0&&<p>最近一次整理未完成：{s.errors.at(-1).error}。已保留原文件。</p>}
  </details>
 </section>;
}
