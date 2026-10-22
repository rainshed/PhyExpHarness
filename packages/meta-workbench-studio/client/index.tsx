import React,{useState} from 'react';
import {api} from '@phyexp/meta-workbench-client';
import {useWorkbench} from './shell/use-workbench';
import {css as componentStyles} from './components/styles';
import {ProviderSettings,providerStyles} from './components/providers';
import {WorkbenchDialogs} from './components/dialogs';
import {CampaignActions,CampaignNotices} from './components/campaign';
import {EvidenceContext} from './components/evidence';
import {CreateCampaign} from './features/create';
import {features,FeaturePage} from './shell/features';
import {studioStyles} from './styles';
import {readingStyles} from './reading-styles';
import {reportGroups} from './readability.mjs';
import {campaignStatus} from './components/campaign-status.mjs';

export const inject=['slots','layout'];
const navigation=features.map(({id,title,icon})=>[id,title,icon]);

export function Studio(){const w=useWorkbench();const [table,setTable]=useState('plugins');const [menu,setMenu]=useState(false);const [evidenceCampaign,setEvidenceCampaign]=useState<any>(null);const {c,view,creating,settingsOpen}=w;
 const status=campaignStatus(c||{});
 const readEvidence=(id:string,context:any=c,offset=0)=>{setEvidenceCampaign(typeof context==='number'?c:context);return w.readEvidence(id,typeof context==='number'?context:offset)};
 const open=(id:string)=>{w.setCreating(false);setMenu(false);w.navigate(id)};
 const tablesProps={campaign:c,onSource:w.readSource,onRename:(v:any)=>w.setRenaming({...v,name:v.displayName.split(' · ').slice(1).join(' · ')}),onStopTrial:(id:string)=>w.act('stop-trial',async()=>{await api('/trials/'+id+'/stop',{});w.setNotice('已请求终止本次实验；失败与用量保留，活动继续。')}),onReport:w.readReport,reportForBatch:(id:string)=>reportGroups(c.reports,c.batches).find((rows:any)=>rows[0].batchId===id)?.[0]?.id,onEvidence:(id:string)=>{const e=c.evidence.find((e:any)=>e.trialId===id);if(e)readEvidence(e.id);else w.setNotice('此实验尚无归档证据。')}};
 return <main className="mh-root studio-root"><style>{componentStyles+providerStyles+studioStyles+readingStyles}</style><aside className={"studio-sidebar"+(menu?" studio-menu-open":"")}><button className="studio-menu-toggle" aria-expanded={menu} onClick={()=>setMenu(!menu)}>☰ 研究空间与导航</button><div className="studio-brand"><span>φ</span><div>PhyExp<small>META HARNESS</small></div></div><label className="studio-picker">研究空间<select aria-label="选择活动" disabled={settingsOpen||!!w.busy} value={w.selected} onChange={e=>{w.setSelected(e.target.value);w.setCreating(false);w.setView('overview')}}><option value="">选择一个活动…</option>{w.list.slice().reverse().map((x:any)=><option key={x.id} value={x.id}>{x.config.name||'进化活动'} · {campaignStatus(x.id===c?.id?c:x).label}</option>)}</select></label><button className="studio-new" disabled={settingsOpen||!!w.busy} onClick={()=>{setMenu(false);w.setCreating(true);w.setError('');w.setFormError('');w.setNavigation((n:number)=>n+1)}}>＋ 新建活动</button><nav aria-label="研究工作台导航">{navigation.map(([id,title,icon])=><button key={id} disabled={settingsOpen} aria-current={!creating&&!settingsOpen&&view===id?'page':undefined} onClick={()=>open(id)}><span aria-hidden="true">{icon}</span>{title}</button>)}</nav><div className="studio-sidebar-bottom"><button disabled={settingsOpen} onClick={()=>{setMenu(false);w.setSettingsOpen(true)}}>⚙ 供应商与模型</button><div className="studio-connection"><span className={w.connected?'mh-dot':'mh-dot offline'}/>{w.connected?'独立后台已连接':'后台连接中断'}</div><small>切换界面不停止后台实验</small></div></aside>
 <div className="studio-workspace"><header className="studio-topbar"><span>研究空间 <span className="studio-slash">/</span> {settingsOpen?'供应商与模型':creating?'新建活动':navigation.find(x=>x[0]===view)?.[1]}</span><span className="mh-muted">{c?.config.fixture?'检查夹具 · 非科学实验':'STUDIO · 阅读版'}</span></header><div className="studio-content">
 {w.error&&<div role="alert" className="mh-alert">{w.error}<button onClick={()=>w.setError('')} aria-label="关闭错误提示">×</button>{!w.connected&&<p>状态可能陈旧；后台按原时限独立运行。重连不会重新启动实验。</p>}</div>}{w.notice&&<p role="status" className="mh-notice">{w.notice}</p>}
 <div hidden={!settingsOpen}>{settingsOpen&&<ProviderSettings api={api} onCatalogChanged={w.refreshModels} onClose={()=>w.setSettingsOpen(false)}/>}</div>
 <div hidden={settingsOpen}>{creating?<CreateCampaign w={w}/>:!c?<section className="mh-empty"><h1>{w.selected?'正在读取活动…':'从一个研究目标开始'}</h1><p>选择已有活动，或创建一个有明确额度的实验。</p></section>:<>
 <header className="studio-campaign" ref={w.heroRef} tabIndex={-1}><div><div className="mh-eyebrow">RESEARCH WORKSPACE</div><h2>{c.config.name||'进化活动'}</h2><div className="studio-model-line"><span className={'mh-badge'+(status.attention?' studio-status-attention':'')}>运行：{status.label}</span><span className="mh-badge">分析：{w.finalReport?.kind==='status_summary'?'未完成':w.finalReport?'已提交':'待提交'}</span><details className="studio-models"><summary>执行配置与版本</summary><span>Solver <b>{c.config.solver.model}</b> · {c.config.solver.reasoningEffort??'无需推理设置'}</span><span>Meta <b>{c.config.meta.model}</b> · {c.config.meta.reasoningEffort??'无需推理设置'}</span><p className="studio-version-line">当前保留：{c.tables.versions.find((v:any)=>v.id===c.retainedCandidateId)?.label||'尚未选择'} · 最新候选：{c.tables.versions.at(-1)?.label||'暂无'} · 最终冻结：{c.tables.versions.find((v:any)=>v.id===c.finalCandidateId)?.label||'尚未冻结'}</p></details></div></div><CampaignActions w={w}/></header>
 <CampaignNotices c={c} onDetails={()=>w.navigate('meta','meta-status')} onResume={()=>w.command('resume')} busy={w.busy} connected={w.connected}/>
 <section ref={w.contentRef} tabIndex={-1} className="studio-page" aria-label="活动内容区">
 <FeaturePage id={view} w={w} c={c} table={table} setTable={setTable} tablesProps={tablesProps} readEvidence={readEvidence} open={open}/>
 </section></>}</div><footer className="studio-footer">PHYEXP / RESEARCH WORKBENCH <span>关闭页面或卸载 UI 不会停止后台</span></footer></div></div><WorkbenchDialogs w={w} evidenceIntro={c&&w.evidence?<EvidenceContext c={evidenceCampaign||c} evidence={w.evidence}/>:null} allowEvidenceDownload/></main>;
}

export function apply(ctx:any){
 ctx.slots.inject('main',()=>ctx.slots.register({name:'main',key:'phyexp-workbench-studio'},()=> <Studio/>));
 ctx.slots.inject('sidebar.footer.action',()=>ctx.slots.register({name:'sidebar.footer.action',id:'phyexp-workbench-studio-nav'},()=> <button aria-label="研究工作台" title="打开研究工作台" style={{width:32,height:32,padding:0,fontSize:22,borderRadius:7}} onClick={()=>ctx.layout.selectPanel('phyexp-workbench-studio')}>φ</button>));
}
