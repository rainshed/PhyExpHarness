import React,{useEffect,useRef} from 'react';
import {readResearchRevision} from '@phyexp/meta-workbench-client';
import {useResearch,useResource} from '@phyexp/meta-workbench-client/react';
import {ResearchSources,ResearchAnnotation} from '../components/research-sources';
import {ResearchPanel,ResearchArticle,SavedResearch,researchStates} from '../components/research';
import {PluginCategories} from '../components/plugin-reading';
import {pluginCategories,filterPlugins,pluginIdentity,pluginVersions} from '../components/plugin-reading.mjs';
import {useReadingState} from '../shell/reading-state';
import {SelectionDecisions} from '../components/selection';
import {PageIntro,ReadingSection,ReadingLimits} from '../components/reading-layout';
import {date} from '../components/common';
import {readableText} from '../readability.mjs';

function PluginStory({w,c,plugin,tablesProps,readEvidence}:any){
 const view=useResearch(c.id,c.researchRevision,0,plugin.id),rows=view.value?.items||[];
 const origin=rows.find((r:any)=>r.developmentRefs?.length);
 const originRef=view.value?.pluginContext?.developmentRef||origin?.developmentRefs?.[0]||rows.find((r:any)=>r.kind==='motivation');
 const source=useResource(c.id+':'+plugin.id);
 useEffect(()=>{if(originRef)source.load(signal=>readResearchRevision(c.id,originRef,signal));else source.clear()},[c.id,plugin.id,originRef?.recordId,originRef?.revision]);
 const latest=view.value?.pluginContext?.latestObservation||rows.find((r:any)=>r.kind==='observation'||r.kind==='turning_point');
 const observation=useResource(c.id+':'+plugin.id+':observation');
 useEffect(()=>{if(latest)observation.load(signal=>readResearchRevision(c.id,latest,signal));else observation.clear()},[c.id,plugin.id,latest?.recordId,latest?.revision]);
 const benefit=observation.value?.record.observations?.filter((o:any)=>o.plugin.pluginKey===plugin.id).map((o:any)=>o.benefit).join('；');
 const used=pluginVersions(c.tables,plugin.id),usedIds=new Set(used.map((v:any)=>v.id));
 const decisions=(c.selectionDecisions||[]).filter((d:any)=>usedIds.has(d.candidateId)),o=source.value;
 return <div className="studio-plugin-story">
  <section className="studio-reading-hero studio-plugin-purpose" aria-label="插件用途与验证状态"><div className="studio-hero-findings"><small className="studio-kicker">它做什么</small><h2>{plugin.displayName}</h2><PluginCategories plugin={plugin}/><p className="studio-hero-lede">{plugin.functionSummary}</p><p className="studio-source-note">用于 {used.map((v:any)=>v.label).join(' / ')||'尚未关联执行版本'} · {pluginIdentity(plugin,c.tables.plugins)}</p></div></section>
  <section className="studio-plugin-mechanism" aria-label="插件工作方式"><small className="studio-kicker">HOW / 工作方式</small><h3>它怎么做？</h3><p>{plugin.mechanism}</p><p className="studio-source-note">{plugin.descriptionSource?.label||'插件用途说明'}{plugin.descriptionSource?.recordedAt?' · 补充于 '+date(plugin.descriptionSource.recordedAt):''}。说明设计行为，实际效果见实验观察。</p></section>
  <ReadingLimits items={latest?.limitations||o?.record.limitations} compact/>
  {view.loading&&<p role="status">正在读取这个插件的解释…</p>}{view.error&&<p role="alert">{view.error}</p>}
  <ReadingSection number="01" title="为什么想到这个办法？" description={o?.record.summary||(source.loading?'正在读取开发时的解释…':'尚未找到开发或采用时的独立解释。')}>
   {source.error&&<p role="alert">{source.error}</p>}{o?<><p className="studio-source-note">采用这一插件时关联的解释 · 修订 {o.revision}，后续认识另行保留。</p><ResearchArticle row={o} c={c} onEvidence={readEvidence} onReport={w.readReport}/></>:<p>已有用途与源码仍可查看；没有记录的动机不补造。</p>}
  </ReadingSection>
  <ReadingSection number="02" title="实际起了什么作用？" description={(latest?researchStates[latest.state]+'：':'')+(benefit||latest?.summary||'还没有独立的实验观察；完成任务不等于插件作用已被验证。')}>
   {latest?<SavedResearch key={latest.recordId+':'+latest.revision} c={c} reference={latest} onEvidence={readEvidence} onReport={w.readReport}/>:<p>可从任务矩阵检查已执行实验及结果。</p>}
  </ReadingSection>
  <ReadingSection number="03" title="哪些版本使用它，为什么采用？" description={used.length?'已用于 '+used.map((v:any)=>v.label).join('、')+'；查看这些版本及其采用依据。':'尚未关联执行版本。'}>
   <div className="mh-actions">{used.map((v:any)=><button key={v.id} onClick={()=>w.compareVersions([v.id])}>{v.displayName} →</button>)}</div>
   <p>一个组合被选中，不代表其中每个插件的收益都已得到证明。</p><SelectionDecisions title="与这个插件相关的版本选择" emptyText="尚未记录这些版本的选择依据。" campaignId={c.id} decisions={decisions} tables={c.tables} readEvidence={readEvidence} onReport={w.readReport}/>
   {used.length>0&&<button onClick={()=>w.compareVersions(used.map((v:any)=>v.id))}>比较使用这个插件的版本 →</button>}
  </ReadingSection>
  <ReadingSection number="04" title="实现细节与准确版本" description="按需核对提示词原文、工具定义、配置和冻结源码。">
   <p>{plugin.name} · {plugin.version}</p><small>内容摘要 {plugin.digest}</small><div className="mh-actions"><button onClick={()=>tablesProps.onSource(plugin)}>查看这一版本的源码与提示词 ↗</button><button onClick={()=>w.compareVersions(used.map((v:any)=>v.id))}>查看使用版本中的配置 →</button></div>
   <details><summary>说明来源与插件声明</summary><pre>{JSON.stringify({descriptionSource:plugin.descriptionSource,categorySource:plugin.categorySource,declaration:plugin.declaration},null,2)}</pre></details>
  </ReadingSection>
  <ReadingSection number="05" title="这个插件的全部研究记录" description="查看其他观察、尝试、认识变化及历史解释修订。">
   <ResearchPanel key={plugin.id} c={c} pluginKey={plugin.id} onEvidence={readEvidence} onReport={w.readReport}/>
  </ReadingSection>
 </div>;
}

export function Page({w,c,tablesProps,readEvidence}:any){
 const plugins=c.tables?.plugins||[];
 const [state,setState]=useReadingState(()=>({selected:plugins[0]?.id||'',category:'all',researchOpen:w.readingTarget==='research'||!plugins.length}),w.readingPages?.lab,w.saveReadingPage?((value:any)=>w.saveReadingPage('lab',value)):undefined);
 const category=state.category||'all',researchOpen=state.researchOpen,filtered=filterPlugins(plugins,category);
 const selected=filtered.some((p:any)=>p.id===state.selected)?state.selected:filtered[0]?.id;
 const setResearchOpen=(researchOpen:boolean)=>setState({researchOpen});
 const library=useRef<HTMLDivElement|null>(null),openButton=useRef<HTMLButtonElement|null>(null),wasOpen=useRef(false);
 useEffect(()=>{if(w.readingTarget?.startsWith('plugin:'))setState({selected:w.readingTarget.slice(7),category:'all',researchOpen:false});else if(w.readingTarget==='research')setResearchOpen(true)},[c.id,w.readingTarget]);
 useEffect(()=>{if(researchOpen){library.current?.focus({preventScroll:true});library.current?.scrollIntoView({block:'start'});wasOpen.current=true}else if(wasOpen.current){openButton.current?.focus({preventScroll:true});wasOpen.current=false}},[researchOpen]);
 const plugin=plugins.find((p:any)=>p.id===selected);
 return <div data-reading-anchor="research" tabIndex={-1} className="studio-plugin-page">
  {researchOpen?<div ref={library} tabIndex={-1} className="studio-research-library">
   <button className="studio-text-link" onClick={()=>setResearchOpen(false)}>← 返回插件与动机</button>
   <PageIntro eyebrow="RESEARCH / 全部探索过程" title="全部研究记录">既看与已有插件相关的研究，也保留尚未形成插件的探索。</PageIntro>
   <ResearchPanel key={c.id} c={c} grouped onEvidence={readEvidence} onReport={w.readReport}/>
  </div>:<>
   {w.pluginReturn&&<button className="studio-text-link" onClick={w.backToComparison}>← 返回刚才的版本对比</button>}
   <PageIntro eyebrow="PLUGINS / 能力、机制与来由" title="每个插件，都有一个来由。">先了解它做什么、怎么做，再看开发动机与实际观察。</PageIntro>
   <nav className="studio-category-filter" aria-label="插件分类">{[['all','全部插件'],...pluginCategories,...(filterPlugins(plugins,'unclassified').length?[['unclassified','分类待补充']]:[])].map(([id,label])=><button key={id} aria-pressed={category===id} onClick={()=>setState({category:id,selected:filterPlugins(plugins,id)[0]?.id||''})}>{label}<span>{filterPlugins(plugins,id).length}</span></button>)}</nav>
   <div className="studio-plugin-toolbar"><nav className="studio-plugin-picker" aria-label="选择要了解的插件">{filtered.map((p:any)=><button key={p.id} aria-pressed={selected===p.id} onClick={()=>setState({selected:p.id})}><strong>{p.displayName}</strong><small>{pluginIdentity(p,plugins)}</small><PluginCategories plugin={p}/></button>)}</nav><button ref={openButton} className="studio-text-link studio-all-research-link" onClick={()=>setResearchOpen(true)}>查看全部研究记录 <span aria-hidden="true">→</span></button></div>
   {plugin?<PluginStory key={c.id+':'+plugin.id} w={w} c={c} plugin={plugin} tablesProps={tablesProps} readEvidence={readEvidence}/>:<p className="mh-muted">{plugins.length?'这个类别下暂无插件，可切换其他类别。':'这个活动尚未形成插件，可查看已保存的研究记录。'}</p>}
  </>}
  <ReadingSection number="↳" title="历史问题来源与补充说明" description="核对其他活动提供的启发，或追加有来源的解释。"><ResearchSources w={w} c={c}/><ResearchAnnotation w={w} c={c}/></ReadingSection>

 </div>;
}
