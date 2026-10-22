import React,{useEffect,useState} from 'react';
import {readResearchRevision} from '@phyexp/meta-workbench-client';
import {useResearch,useResource} from '@phyexp/meta-workbench-client/react';
import {ResearchSources,ResearchAnnotation} from '../components/research-sources';
import {ResearchPanel,ResearchArticle,SavedResearch,researchStates} from '../components/research';
import {HarnessTables} from '../components/tables';
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
 const used=c.tables.versions.filter((v:any)=>v.plugins.some((p:any)=>p.pluginId===plugin.id));
 const decision=c.selectionDecisions?.at(-1),o=source.value;
 return <div className="studio-plugin-story">
  <section className="studio-reading-hero studio-plugin-purpose" aria-label="插件用途与验证状态"><div className="studio-hero-findings"><small className="studio-kicker">用途 / {plugin.displayName}</small><h2>{plugin.functionSummary}</h2><p className="studio-source-note">用于 {used.map((v:any)=>v.label).join(' / ')||'尚未关联执行版本'} · {plugin.version}</p></div><div className="studio-hero-choice"><small className="studio-kicker">这次研究中的状态</small><h3>{latest?researchStates[latest.state]:'实际作用尚待确认'}</h3><p>{readableText(benefit||latest?.summary)||'加载、触发、行为变化与任务收益分开核对。'}</p>{latest&&<small>最近观察记录于 {date(latest.recordedAt)}</small>}</div></section>
  <ReadingLimits items={latest?.limitations||o?.record.limitations} compact/>
  {view.loading&&<p role="status">正在读取这个插件的解释…</p>}{view.error&&<p role="alert">{view.error}</p>}
  <ReadingSection number="01" title="为什么想到这个办法？" description={o?.record.summary||(source.loading?'正在读取开发时的解释…':'尚未找到开发或采用时的独立解释。')}>
   {source.error&&<p role="alert">{source.error}</p>}{o?<><p className="studio-source-note">采用这一插件时关联的解释 · 修订 {o.revision}，后续认识另行保留。</p><ResearchArticle row={o} c={c} onEvidence={readEvidence} onReport={w.readReport}/></>:<p>已有用途与源码仍可查看；没有记录的动机不补造。</p>}
  </ReadingSection>
  <ReadingSection number="02" title="实际起了什么作用？" description={benefit||latest?.summary||'还没有独立的实验观察；完成任务不等于插件作用已被验证。'}>
   {latest?<SavedResearch key={latest.recordId+':'+latest.revision} c={c} reference={latest} onEvidence={readEvidence} onReport={w.readReport}/>:<p>可从任务矩阵检查已执行实验及结果。</p>}
  </ReadingSection>
  <ReadingSection number="03" title="为什么保留，或暂不采用？" description={decision?.summary||'本活动尚未记录版本选择。'}>
   <p>这里展示本活动的版本取舍。一个组合被选中，不代表其中每个插件的收益都已得到证明。</p><SelectionDecisions campaignId={c.id} decisions={decision?[decision]:[]} tables={c.tables} readEvidence={readEvidence} onReport={w.readReport}/>
   <button onClick={()=>w.navigate('compare')}>比较全部版本与实验结果 →</button>
  </ReadingSection>
  <ReadingSection number="04" title="实现方式与准确版本" description="需要时再查看机制、内容身份及冻结源码。">
   <p>{plugin.mechanism}</p><p>{plugin.name} · {plugin.version}</p><small>内容摘要 {plugin.digest}</small><div className="mh-actions"><button onClick={()=>tablesProps.onSource(plugin)}>查看这一版本的源码 ↗</button></div>
  </ReadingSection>
  <ReadingSection number="05" title="这个插件的全部研究记录" description="查看其他观察、尝试、认识变化及历史解释修订。">
   <ResearchPanel key={plugin.id} c={c} pluginKey={plugin.id} onEvidence={readEvidence} onReport={w.readReport}/>
  </ReadingSection>
 </div>;
}

export function Page({w,c,table,setTable,tablesProps,readEvidence}:any){
 const plugins=c.tables?.plugins||[];
 const [selected,setSelected]=useState(w.readingTarget==='research'?'research':plugins[0]?.id||'research');
 useEffect(()=>setSelected(w.readingTarget==='research'?'research':plugins[0]?.id||'research'),[c.id,w.readingTarget]);
 const plugin=plugins.find((p:any)=>p.id===selected);
 return <div data-reading-anchor="research" tabIndex={-1} className="studio-plugin-page">
  <PageIntro eyebrow="PLUGINS / 从动机理解能力" title="每个插件，都有一个来由。">先了解它解决什么问题，再看实际发生了什么。</PageIntro>
  <nav className="studio-plugin-picker" aria-label="选择要了解的插件">{plugins.map((p:any)=><button key={p.id} aria-pressed={selected===p.id} onClick={()=>setSelected(p.id)}><strong>{p.displayName}</strong><small>{p.version}{plugins.filter((x:any)=>x.name===p.name&&x.version===p.version).length>1?' · 内容 '+p.digest?.slice(0,8):''}</small></button>)}<button aria-pressed={selected==='research'} onClick={()=>setSelected('research')}><strong>全部研究与未成形的尝试</strong><small>保留失败、放弃和没有插件的方向</small></button></nav>
  {plugin?<PluginStory key={c.id+':'+plugin.id} w={w} c={c} plugin={plugin} tablesProps={tablesProps} readEvidence={readEvidence}/>:<ResearchPanel key={c.id} c={c} onEvidence={readEvidence} onReport={w.readReport}/>}
  <ReadingSection number="↳" title="历史问题来源与补充说明" description="核对其他活动提供的启发，或追加有来源的解释。"><ResearchSources w={w} c={c}/><ResearchAnnotation w={w} c={c}/></ReadingSection>
  <ReadingSection number="↳" title="版本、配置与代码继承" description="查看全部插件组合、父版本、名称和配置。" open={table==='versions'}><nav className="mh-tabs" aria-label="实验工作区">{[['plugins','插件与配置'],['versions','版本详情与血缘']].map(([id,label])=><button key={id} className={table===id?'active':''} aria-pressed={table===id} onClick={()=>setTable(id)}>{label}</button>)}</nav><HarnessTables tables={c.tables} {...tablesProps} section={table} onSectionChange={setTable}/></ReadingSection>
 </div>;
}
