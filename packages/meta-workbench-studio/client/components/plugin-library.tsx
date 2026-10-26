import React,{useState,useEffect,useRef} from 'react';
import {useResource} from '@phyexp/meta-workbench-client/react';
import {libraryClient,libraryWrites} from '@phyexp/meta-workbench-client/plugin-library';
const client=libraryClient();
const json=(value:any)=>JSON.stringify(value,null,2);
const origin=(s:any)=>s.kind==='platform-template'?'平台提供':`${s.campaignName||s.campaignId||'来源未标注'} / ${s.candidateLabel||s.candidateId||s.checkId||'源码快照'}${s.available===false?' · 来源活动已不可用':''}`;

export function LibraryBrowser({selection,onChange,refresh=0,manage=false}:any){
 const [query,setQuery]=useState(''),[offset,setOffset]=useState(0),[deleted,setDeleted]=useState(false),[id,setId]=useState(''),[file,setFile]=useState('');
 const list=useResource('library-list'),detail=useResource('library-detail:'+id),source=useResource('library-source:'+id),preview=useResource('library-delete:'+id);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0);
 const [writes]=useState(()=>libraryWrites(localStorage));const active=useRef(true);
 useEffect(()=>{active.current=true;return()=>{active.current=false}},[]);
 useEffect(()=>{list.load(signal=>client.page({query,offset,includeDeleted:deleted},signal))},[query,offset,deleted,refresh,revision]);
 useEffect(()=>{setFile('');preview.clear();if(id)detail.load(signal=>client.detail(id,undefined,signal))},[id,revision]);
 useEffect(()=>{if(id&&file)source.load(signal=>client.detail(id,file,signal));else source.clear()},[id,file]);
 const change=async(action:string)=>{if(busy)return;setBusy(true);setError('');try{
  await writes.send('/plugin-library/'+id+'/change',{action,versions:preview.value.versions});
  if(active.current){preview.clear();setOffset(0);setRevision(v=>v+1);}
 }catch(e:any){if(active.current)setError(e.message)}finally{if(active.current)setBusy(false)}};
 const retry=async()=>{if(busy)return;setBusy(true);setError('');try{await writes.retry();if(active.current){preview.clear();setOffset(0);setRevision(v=>v+1)}}catch(e:any){if(active.current)setError(e.message)}finally{if(active.current)setBusy(false)}};
 const chosen=(selection?.plugins||[]).some((p:any)=>p.id===id),row=detail.value;
 const select=()=>onChange({...selection,plugins:chosen?selection.plugins.filter((p:any)=>p.id!==id):[...selection.plugins,{id,config:row.manifest.assembly?.defaultConfig||{}}]});
 return <div className="library-browser"><div className="mh-actions"><label>搜索插件<input value={query} placeholder="名称、用途或来源" onChange={e=>{setQuery(e.target.value);setOffset(0)}}/></label>{manage&&<label className="mh-check"><input type="checkbox" checked={deleted} onChange={e=>{setDeleted(e.target.checked);setOffset(0)}}/>包含已删除版本</label>}</div>
 {list.value?.publicationIssues?.map((v:any)=><p role="alert" key={v.id}>{v.reason}</p>)}{list.error&&<p role="alert">{list.error}</p>}{list.loading&&<p role="status">读取插件库…</p>}
 <div className="library-columns"><div><p>{list.value?.total??0} 个版本</p>{list.value?.items.map((p:any)=><button type="button" className="library-row" aria-pressed={id===p.id} key={p.id} onClick={()=>setId(p.id)}><b>{p.displayName} · {p.version}</b><small>{p.id.slice(0,12)} · {p.deleted?'已删除':p.compatibility.state==='declared'?'可选择，待组合检查':'需要适配'}{selection?.plugins.some((v:any)=>v.id===p.id)?' · 已选择':''}</small><span>{p.description||'用途尚未说明'}</span></button>)}<div className="mh-actions"><button type="button" disabled={!offset||list.loading} onClick={()=>setOffset(Math.max(0,offset-50))}>上一页</button><button type="button" disabled={list.value?.nextOffset==null||list.loading} onClick={()=>setOffset(list.value.nextOffset)}>下一页</button></div></div>
 <div>{detail.error&&<p role="alert">{detail.error}</p>}{row&&<><h3>{row.displayName} · {row.version}</h3><p className="library-digest">内容摘要：{row.id}</p><p>{row.description||'用途尚未说明'}</p><p>已保存 · 所在组合构建：{row.buildStatus==='passed'?'曾通过':row.buildStatus==='failed'?'失败':'尚未检查'} · {row.runtimeStatus==='attempted'?'所在组合已尝试运行':'尚无运行记录'}</p><p className="mh-notice">这些状态不能证明单个插件有效。历史成绩只属于当时的组合和实验条件。</p><p>{row.compatibility.reason}</p><p>{row.manifest.mechanism||'机制尚未说明'}</p><p>限制：{Array.isArray(row.manifest.limitations)?row.manifest.limitations.join('；'):typeof row.manifest.limitations==='string'?row.manifest.limitations:'尚未说明'}</p>
 {selection&&<button type="button" disabled={!chosen&&(row.deleted||row.compatibility.state!=='declared')} onClick={select}>{chosen?'从 H0 移除':'加入 H0'}</button>}
 <details><summary>配置规范与依赖</summary><pre>{json(row.manifest.assembly||{})}</pre></details><details><summary>来源（{(row.origins||row.sources).length}）</summary>{(row.origins||row.sources).map((s:any,i:number)=><p key={i}>{origin(s)}</p>)}</details>
 {row.checks.length>0&&<details><summary>构建记录与失败原因</summary>{row.checks.map((c:any,i:number)=><p key={i}>{c.candidateId||c.checkId} · {c.status}{c.error&&' · '+c.error}</p>)}</details>}
 {row.runs?.length>0&&<details><summary>组合运行记录（{row.runs.length}）</summary>{row.runs.map((r:any)=><p key={r.id}>{r.campaignId} / {r.candidateId} · {r.task} · {r.state} · 官方分数 {r.score??'未评分'}</p>)}</details>}
 {row.sourceStatus==='reclaimed'?<p>源码已按无引用清理规则释放；需要先从仍存在的历史快照补录，再明确重新导入。</p>:<label>读取源码<select value={file} onChange={e=>setFile(e.target.value)}><option value="">选择文件…</option>{row.files.map((f:string)=><option key={f}>{f}</option>)}</select></label>}{source.error&&<p role="alert">{source.error}</p>}{source.value&&<pre className="library-source">{source.value.content}</pre>}
 {manage&&<div className="mh-actions"><button type="button" disabled={busy} onClick={()=>preview.load(signal=>client.previewDelete(id,'version',signal))}>{row.deleted?'核对重新导入':'删除此版本…'}</button>{!row.deleted&&<button type="button" disabled={busy} onClick={()=>preview.load(signal=>client.previewDelete(id,'plugin',signal))}>删除同名插件全部版本…</button>}</div>}
 {preview.error&&<p role="alert">{preview.error}</p>}{preview.value&&<section className="mh-notice"><p>{row.deleted?'将此准确版本重新放回可选库；仍需在具体组合中检查，历史成绩不变。':preview.value.message}</p><p>范围：{preview.value.versions.length} 个版本。{!row.deleted&&'可释放空间：待核算。'}</p>{preview.value.versions.map((v:any)=><p key={v.id}>{v.id.slice(0,12)} · 活动引用 {v.references.campaigns.length} · 库依赖 {v.references.plugins.length} · 冻结候选 {v.references.candidateSnapshots.length}</p>)}<button type="button" disabled={busy} onClick={()=>change(row.deleted?'restore':'delete')}>{row.deleted?'明确重新导入此版本':'确认从库中删除'}</button><button type="button" disabled={busy} onClick={preview.clear}>取消</button></section>}{error&&<p role="alert">{error}</p>}{writes.pending()&&<button type="button" disabled={busy} onClick={retry}>用原请求核对未确认操作</button>}</>}{!row&&!detail.loading&&<p>选择一个版本，阅读用途、配置、源码与来源。</p>}</div></div></div>;
}

export function H0Selector({value,onChange,onReady,uncertain=false}:any){
 const preset=useResource('h0-defaults'),checked=useResource('h0-preview');const [invalidIds,setInvalidIds]=useState<any>({});const invalid=(value?.plugins||[]).some((p:any)=>invalidIds[p.id]);
 const fingerprint=JSON.stringify(value);
 useEffect(()=>{preset.load(client.defaults)},[]);
 useEffect(()=>{checked.clear();onReady(false)},[fingerprint,invalid]);
 const apply=(plugins:any[])=>{setInvalidIds({});onChange({version:preset.value.version,templateId:preset.value.templateId,plugins})};
 const check=async()=>{const result=await checked.load(signal=>client.preview(value,signal));if(result.current&&!result.error)onReady(true)};
 return <section><h3>本活动起点 H0</h3><p>选择准确插件版本及配置。Meta 只能看到这些内容及本活动的新成果；库中的其他插件不会提供给它。</p>{uncertain&&!value&&<p className="mh-notice">存在尚未确认的历史创建请求，可按原内容继续核对；重新选择将形成新的创建意图。</p>}{preset.error&&<p role="alert">{preset.error}</p>}{preset.value&&<><div className="mh-actions"><button type="button" disabled={preset.value.missing.length>0} onClick={()=>apply(preset.value.plugins)}>使用推荐预设（含恢复插件）</button><button type="button" onClick={()=>apply([])}>使用最小模板（不含可选插件）</button></div>{preset.value.missing.length>0&&<p>推荐预设的插件已被删除。可使用最小模板，或在插件库明确重新导入。</p>}</>}
 {value&&<><p className="library-digest">基础模板：{value.templateId}</p><h4>已选插件（{value.plugins.length}）</h4><p>依赖须逐项加入；不会静默补选。恢复插件控制请求与响应恢复，取消选择后保留框架基本工具错误反馈。</p>{value.plugins.map((p:any)=><SelectedPlugin key={p.id} chosen={p} onChange={(config:any)=>onChange({...value,plugins:value.plugins.map((x:any)=>x.id===p.id?{...x,config}:x)})} onRemove={()=>onChange({...value,plugins:value.plugins.filter((x:any)=>x.id!==p.id)})} onInvalid={(bad:boolean)=>setInvalidIds((old:any)=>old[p.id]===bad?old:{...old,[p.id]:bad})}/>)}<LibraryBrowser selection={value} onChange={onChange}/><button type="button" disabled={invalid||checked.loading} onClick={check}>{checked.loading?'核对中…':'核对组合与配置'}</button>{checked.error&&<p role="alert">{checked.error}</p>}{checked.value&&<p role="status" className="library-digest">选择核对通过 · 组合 {checked.value.compositionId}。创建后在隔离环境构建并检查实际加载，不调用模型。</p>}</>}
 </section>;
}
function SelectedPlugin({chosen,onChange,onRemove,onInvalid}:any){
 const info=useResource('selected:'+chosen.id);const [text,setText]=useState(json(chosen.config)),[error,setError]=useState('');
 useEffect(()=>{info.load(signal=>client.detail(chosen.id,undefined,signal))},[chosen.id]);
 useEffect(()=>{setText(json(chosen.config));setError('');onInvalid(false)},[JSON.stringify(chosen.config)]);
 return <fieldset><legend>{info.value?.displayName||chosen.id.slice(0,12)} · {info.value?.version}</legend><p className="library-digest">{chosen.id}</p>{info.error&&<p role="alert">{info.error}</p>}{info.value?.deleted&&<p role="alert">此版本已删除，请移除或在库中重新导入。</p>}<label>插件配置（JSON）<textarea rows={6} value={text} onChange={e=>{setText(e.target.value);try{const config=JSON.parse(e.target.value);onChange(config);setError('');onInvalid(false)}catch{setError('配置不是合法 JSON');onInvalid(true)}}}/></label>{error&&<p role="alert">{error}</p>}{info.value?.manifest.assembly?.requires?.length>0&&<p className="library-digest">需要显式加入的版本：{info.value.manifest.assembly.requires.join('、')}</p>}<button type="button" onClick={onRemove}>移除此插件</button></fieldset>;
}

export function H0Summary({campaign}:any){
 const data=useResource('activity-h0:'+campaign.id);
 useEffect(()=>{data.load(signal=>client.h0(campaign.id,signal))},[campaign.id,campaign.h0CandidateId,campaign.counts?.trials,campaign.counts?.startedTrials]);
 const h=data.value;return <section className="mh-card"><h3>H0 · 本活动选定的起点</h3>{data.error&&<p role="alert">{data.error}</p>}{h&&<><p>{h.validation}</p>{h.legacy?<p>历史活动沿用原冻结起点和协议。</p>:<><p className="library-digest">组合摘要：{h.compositionId}</p><p className="library-digest">基础模板：{h.templateId}</p><p>跨活动使用相同内容不会产生新实现；本活动成绩单独统计。</p>{h.plugins.length===0&&<p>最小模板，无可选插件。</p>}{h.plugins.map((p:any)=><details key={p.id}><summary>{p.displayName} · {p.version}{p.deletedFromLibrary?' · 已从可选库删除，活动保留冻结内容':''}</summary><p className="library-digest">{p.id}</p><pre>{json(p.config)}</pre>{p.sources.map((s:any,i:number)=><p key={i}>{origin(s)}</p>)}</details>)}</>}</>}</section>;
}
