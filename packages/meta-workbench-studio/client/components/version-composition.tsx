import React from 'react';
import {PluginCategories} from './plugin-reading';
import {pluginIdentity} from './plugin-reading.mjs';

export function VersionComposition({versions,plugins=[],expanded=[],onExpanded,onPlugin,onRename,canRename=true}:any){
 if(!versions.length)return <p className="mh-muted">尚未形成可对比的执行版本。</p>;
 const lookup=new Map<string,any>(plugins.map((p:any)=>[p.id,p]));
 const link=(v:any,m:any,full=false)=>{
  const p=lookup.get(m.pluginId);
  return p?<><button className="studio-composition-plugin" data-plugin-link={v.id+':'+(full?'full:':'')+p.id} onClick={()=>onPlugin(p.id)}>{p.displayName}<span aria-hidden="true"> ↗</span></button><PluginCategories plugin={p}/></>:<span>插件记录缺失</span>;
 };
 return <section className="studio-version-compositions" aria-label="所选版本的插件组合">
  <h3>这些版本如何组合？</h3><p className="mh-muted">插件、各自的配置和加载顺序，共同组成一个执行版本。</p>
  <div className="studio-matrix studio-composition-matrix" data-many={versions.length>3} style={{'--versions':versions.length} as any}>
   <div className="studio-matrix-row studio-matrix-head"><div>执行版本</div>{versions.map((v:any)=><div key={v.id}><strong>{v.label}</strong><small>{v.displayName?.replace(v.label+' · ','')}</small></div>)}</div>
   <div className="studio-matrix-row studio-composition-row"><div className="studio-task-name">插件组合</div>{versions.map((v:any)=><div key={v.id} className="studio-composition-cell"><strong className="studio-cell-version">{v.displayName||v.label}</strong>
    {!v.plugins.length?<p className="mh-muted">原始基线 · 无额外插件</p>:<><ul>{v.plugins.slice(0,3).map((m:any)=><li key={m.pluginId}>{link(v,m)}</li>)}</ul>{v.plugins.length>3&&<p className="mh-muted">另有 {v.plugins.length-3} 个插件，完整组合见下方。</p>}</>}
    <details open={expanded.includes(v.id)} onToggle={e=>{const next=e.currentTarget.open;if(next!==expanded.includes(v.id))onExpanded(next?[...expanded,v.id]:expanded.filter((id:string)=>id!==v.id))}}><summary>{v.label} · 组合详情</summary>
     {!v.plugins.length?<p>这个版本没有额外插件配置。</p>:<><p className="studio-source-note">以下按实际加载顺序排列；配置来自这个执行版本。</p><ol>{v.plugins.map((m:any)=>{const p=lookup.get(m.pluginId);return <li key={m.pluginId} value={m.order}>{link(v,m,true)}{p&&<><p className="studio-source-note">{pluginIdentity(p,plugins)}</p><details><summary>准确内容身份</summary><small>{p.name}<br/>{p.digest||'内容摘要未记录'}</small></details></>}<details><summary>查看此版本中的配置</summary><pre>{JSON.stringify(m.config,null,2)}</pre></details></li>})}</ol></>}
     <details><summary>版本来源与准确身份</summary><p>来源版本：{v.parentId?(v.parentLabel||'记录缺失'):'起点'}</p><small>冻结组合：{v.bundleId||'未记录'}</small></details>
    </details>{onRename&&<button className="studio-text-link" disabled={!canRename} onClick={()=>onRename(v)}>修改 {v.label} 名称</button>}
   </div>)}</div>
  </div>
 </section>;
}
