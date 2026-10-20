import React,{useState,useEffect,useRef} from 'react';
import {configError,numericConfig} from './form.mjs';
import {loadGoalDraft} from './goal.mjs';
import {readModelCatalog} from './model-catalog.mjs';
import {createAttempt,createAttemptStorageKey} from './create-attempt.mjs';
import {NumberField} from './fields';
import {defaults,api,key} from './common';
function loadDraft(){try{return loadGoalDraft(localStorage,defaults)}catch{return defaults}}
function loadCreateAttempt(){try{return JSON.parse(localStorage.getItem(createAttemptStorageKey)||'null')}catch{return null}}
export function useWorkbench(){
 const [list,setList]=useState<any[]>([]),[selected,setSelected]=useState(()=>localStorage.getItem('phyexp-campaign')||''),[c,setC]=useState<any>(null),[view,setView]=useState('overview'),[creating,setCreating]=useState(false),[config,setConfig]=useState<any>(loadDraft),[error,setError]=useState(''),[connected,setConnected]=useState(false),[busy,setBusy]=useState(''),[events,setEvents]=useState<any[]>([]),[report,setReport]=useState<any>(null),[evidence,setEvidence]=useState<any>(null),[limits,setLimits]=useState<any>(null),[notice,setNotice]=useState('');
 const [models,setModels]=useState<any[]>([]),[modelCatalogNote,setModelCatalogNote]=useState(''),[settingsOpen,setSettingsOpen]=useState(false);
 const catalogRevision=useRef<number|undefined>(undefined);
 const pendingCreate=useRef<any>(loadCreateAttempt());
 const acceptCatalog=(catalog:any)=>{if(catalog.revision!=null&&catalogRevision.current!=null&&catalog.revision<catalogRevision.current)return;const parsed=readModelCatalog(catalog);catalogRevision.current=catalog.revision;setModels(parsed.models);setModelCatalogNote(parsed.note)};
 const refreshModels=async()=>acceptCatalog(await api('/models'));
 const [source,setSource]=useState<any>(null),[renaming,setRenaming]=useState<any>(null);
 const mounted=useRef(true),detailRequest=useRef(0),detailTrigger=useRef<HTMLElement|null>(null);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;detailRequest.current++;reportRequest.current++}},[]);
 const cursor=useRef(0);const active=useRef('');active.current=selected;
 const [formError,setFormError]=useState(''),[limitsError,setLimitsError]=useState(''),[reportLoading,setReportLoading]=useState(false),[reportError,setReportError]=useState(''),[navigation,setNavigation]=useState(0);
 const contentRef=useRef<HTMLElement>(null),formRef=useRef<HTMLElement>(null),formErrorRef=useRef<HTMLDivElement>(null),heroRef=useRef<HTMLElement>(null),reportRequest=useRef(0),actionLock=useRef(false);
 const focus=(element:HTMLElement|null)=>{element?.scrollIntoView({block:'start',behavior:'instant'});element?.focus({preventScroll:true})};
 const navigate=(next:string)=>{setView(next);setNavigation(n=>n+1)};
 useEffect(()=>{try{localStorage.setItem('phyexp-draft',JSON.stringify(config))}catch{}},[config]);
 useEffect(()=>{if(navigation)focus(creating?formRef.current:contentRef.current)},[navigation,creating]);
 useEffect(()=>{if(formError)focus(formErrorRef.current)},[formError]);
 useEffect(()=>{if(view==='reports'&&(report||reportError))focus(contentRef.current)},[report,reportError]);
 async function refresh(id=selected){if(!mounted.current)return;const items=await api('/campaigns');if(!mounted.current)return;setList(items);setConnected(true);if(id){const current=await api('/campaigns/'+id);if(mounted.current&&active.current===id)setC(current);} }
 useEffect(()=>{let live=true,loading=false;const controller=new AbortController();cursor.current=0;detailRequest.current++;setSource(null);setRenaming(null);setLimits(null);setEvents([]);setReport(null);setReportError('');setReportLoading(false);reportRequest.current++;setEvidence(null);setC(null);if(selected)localStorage.setItem('phyexp-campaign',selected);const poll=async()=>{if(loading)return;loading=true;try{const [items,catalog]=await Promise.all([api('/campaigns',undefined,controller.signal),api('/models',undefined,controller.signal)]);if(!live)return;acceptCatalog(catalog);setList(items);setConnected(true);if(selected&&!items.some((x:any)=>x.id===selected)){setSelected('');localStorage.removeItem('phyexp-campaign');return;}if(selected){const [current,newEvents]=await Promise.all([api('/campaigns/'+selected,undefined,controller.signal),api('/campaigns/'+selected+'/events?after='+cursor.current,undefined,controller.signal)]);if(!live)return;setC(current);if(newEvents.length){cursor.current=newEvents.at(-1).seq;setEvents(old=>[...old,...newEvents].slice(-100));}}}catch(e:any){if(live){setConnected(false);setError(e.message)}}finally{loading=false}};poll();const timer=setInterval(poll,2000);return()=>{live=false;controller.abort();clearInterval(timer)}} ,[selected]);
 async function act(label:string,fn:()=>Promise<any>){if(actionLock.current)return;actionLock.current=true;setBusy(label);setError('');setNotice('');try{await fn();await refresh(active.current);}catch(e:any){setError(e.message)}finally{actionLock.current=false;setBusy('')}}
 const command=(action:string,changes?:any)=>act(action,async()=>{await api('/campaigns/'+selected+'/control',{action,changes,expectedRevision:c.revision,idempotencyKey:key()});setNotice('操作已受理，以下状态来自后台。')});
 function field(name:string,label:string,note?:string){return <NumberField key={name} label={label} value={config[name]} note={note} onChange={(value:string)=>{setConfig({...config,[name]:value});setFormError('')}}/>}
 async function readReport(id:string){
  const request=++reportRequest.current;setCreating(false);setReport(null);setReportError('');setReportLoading(true);navigate('reports');
  try{const next=await api('/reports/'+id);if(request===reportRequest.current)setReport(next)}
  catch(e:any){if(request===reportRequest.current)setReportError('报告读取失败：'+e.message+'。请重新选择报告重试。')}
  finally{if(request===reportRequest.current)setReportLoading(false)}
 }
 async function createCampaign(){
  if(actionLock.current)return;
  const problem=configError(config);setFormError(problem);if(problem){focus(formErrorRef.current);return}
  actionLock.current=true;setBusy('create');setError('');setNotice('');
  const values=numericConfig(config);pendingCreate.current=createAttempt(values,pendingCreate.current,key);
  try{localStorage.setItem(createAttemptStorageKey,JSON.stringify(pendingCreate.current))}catch{}
  try{const next=await api('/campaigns',{config:values,idempotencyKey:pendingCreate.current.key,modelCatalogRevision:catalogRevision.current});pendingCreate.current=null;try{localStorage.removeItem(createAttemptStorageKey)}catch{}setSelected(next.id);active.current=next.id;setCreating(false);setView('overview');setNotice('活动已创建。后台正在准备任务环境并检查基线，完成后即可启动。');setC(next);requestAnimationFrame(()=>focus(heroRef.current));}
  catch(e:any){setFormError('创建未完成：'+e.message+'。配置已保留，可以重试；不需要重新填写。')}
  finally{actionLock.current=false;setBusy('')}
 }
 async function saveLimits(){
  const problem=configError(limits);setLimitsError(problem);if(problem||actionLock.current)return;
  actionLock.current=true;setBusy('limits');
  try{const changes:any={};const values=numericConfig(limits);for(const k of ['maxRounds','maxTrials','concurrency','wallTimeSeconds','trialTimeSeconds','softTokenLimit','reserveSeconds','reserveTokens','stopMode','drainGraceSeconds'])if(!Object.is(values[k],c.config[k]))changes[k]=values[k];if(!Object.keys(changes).length){setLimits(null);setNotice('上限没有变化。');return}await api('/campaigns/'+selected+'/control',{action:'limits',changes,expectedRevision:c.revision,idempotencyKey:key()});setLimits(null);setNotice('活动上限已保存。已启动任务仍受其启动时条件约束；提高额度不自动延长现有进程。');await refresh(active.current)}
  catch(e:any){setLimitsError('保存未完成：'+e.message)}finally{actionLock.current=false;setBusy('')}
 }
 function closeDetails(){detailRequest.current++;setSource(null);setEvidence(null)}
 async function readEvidence(id:string,offset=0){if(actionLock.current)return;if(!evidence&&!source)detailTrigger.current=document.activeElement as HTMLElement;const request=++detailRequest.current;const campaign=active.current;await act('evidence',async()=>{const data=await api('/evidence/'+id+'?offset='+offset+'&limit=16000');if(mounted.current&&request===detailRequest.current&&campaign===active.current){setSource(null);setEvidence(data)}})}
 async function readSource(p:any,file?:string){if(actionLock.current)return;if(!evidence&&!source)detailTrigger.current=document.activeElement as HTMLElement;const request=++detailRequest.current;const campaign=active.current;await act('source',async()=>{const data=await api('/candidates/'+p.candidateId+'/plugins/'+p.id+(file?'?file='+encodeURIComponent(file):''));if(mounted.current&&request===detailRequest.current&&campaign===active.current){setEvidence(null);setSource({...data,plugin:p});}})}
 const latestReports=c?[...new Map(c.reports.map((r:any)=>[r.batchId||r.kind,r])).values()] as any[]:[];
 const finalReport=latestReports.find((r:any)=>r.kind==='final')||latestReports.find((r:any)=>r.kind==='status_summary');
 const h0Ready=c?.candidates.some((x:any)=>!x.plugins.length&&x.check.status==='passed');
 return {list,setList,selected,setSelected,c,setC,view,setView,creating,setCreating,config,setConfig,error,setError,connected,setConnected,busy,setBusy,events,setEvents,report,setReport,evidence,setEvidence,limits,setLimits,notice,setNotice,models,modelCatalogNote,settingsOpen,setSettingsOpen,refreshModels,source,setSource,renaming,setRenaming,formError,setFormError,limitsError,setLimitsError,reportLoading,reportError,setNavigation,contentRef,formRef,formErrorRef,heroRef,detailTrigger,focus,navigate,refresh,act,command,readReport,createCampaign,saveLimits,closeDetails,readEvidence,readSource,latestReports,finalReport,h0Ready};
}
