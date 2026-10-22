import {useState,useEffect,useRef} from 'react';
import {api,defaults,createDraftStore,createCommands} from '@phyexp/meta-workbench-client';
import {useCampaignData,useResource} from '@phyexp/meta-workbench-client/react';

// Studio owns presentation and focus. The public client owns reads and commands.
export function useWorkbench(){
 const [session]=useState(()=>{try{return {store:createDraftStore(localStorage,'studio',defaults,{legacy:true}),error:''}}catch(e:any){return {store:null,error:'无法读取或保存活动草稿：'+e.message}}});
 const [selected,setSelected]=useState(()=>session.store?.read().selected||'');
 const [config,setConfig]=useState<any>(()=>session.store?.read().config||defaults);
 const data=useCampaignData(selected),c=data.campaign;
 const [readingTarget,setReadingTarget]=useState('');
 const [view,setView]=useState('overview'),[creating,setCreating]=useState(false),[settingsOpen,setSettingsOpen]=useState(false);
 const [error,setError]=useState(session.error),[busy,setBusy]=useState(''),[notice,setNotice]=useState('');
 const [limits,setLimits]=useState<any>(null),[renaming,setRenaming]=useState<any>(null);
 const [formError,setFormError]=useState(''),[limitsError,setLimitsError]=useState(''),[navigation,setNavigation]=useState(0);
 const report=useResource(selected),detail=useResource(selected);
 const contentRef=useRef<HTMLElement>(null),formRef=useRef<HTMLElement>(null),formErrorRef=useRef<HTMLDivElement>(null),heroRef=useRef<HTMLElement>(null),detailTrigger=useRef<HTMLElement|null>(null);
 const mounted=useRef(true),actionLock=useRef(false);
 const commands=createCommands({store:session.store});
 const focus=(element:HTMLElement|null)=>{element?.scrollIntoView({block:'start',behavior:'instant'});element?.focus({preventScroll:true})};
 const navigate=(next:string,target='')=>{setReadingTarget(target);setView(next);setNavigation(n=>n+1)};
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 useEffect(()=>{if(data.error)setError(data.error)},[data.error]);
 useEffect(()=>{if(data.selectionMissing)setSelected('')},[data.selectionMissing]);
 useEffect(()=>{try{session.store?.update({config,selected})}catch(e:any){setError('无法保存活动草稿：'+e.message)}},[config,selected]);
 useEffect(()=>{setLimits(null);setRenaming(null)},[selected]);
 useEffect(()=>{if(navigation)focus(creating?formRef.current:(readingTarget?contentRef.current?.querySelector<HTMLElement>('[data-reading-anchor="'+readingTarget+'"]'):null)||contentRef.current)},[navigation,creating]);
 useEffect(()=>{if(formError)focus(formErrorRef.current)},[formError]);
 useEffect(()=>{if(view==='reports'&&(report.value||report.error))focus(contentRef.current)},[report.value,report.error]);
 async function act(label:string,fn:()=>Promise<any>){
  if(actionLock.current)return;actionLock.current=true;setBusy(label);setError('');setNotice('');
  try{await fn();if(mounted.current)await data.refresh();}catch(e:any){if(mounted.current)setError(e.message)}
  finally{actionLock.current=false;if(mounted.current)setBusy('')}
 }
 const command=(action:string,changes?:any)=>act(action,async()=>{
  await commands.control(c,action,changes);
  if(mounted.current)setNotice('操作已受理，以下状态来自后台。');
 });
 async function readReport(id:string){
  setCreating(false);navigate('reports');await report.load((signal)=>api('/reports/'+id,undefined,signal));
 }
 async function createCampaign(){
  if(actionLock.current)return;actionLock.current=true;setBusy('create');setError('');setNotice('');
  try{
   if(!session.store)throw Error(session.error);
   const next=await commands.create(config,data.catalogRevision);
   if(!mounted.current)return;
   setSelected(next.id);setCreating(false);setView('overview');setFormError('');
   setNotice('活动已创建。后台正在准备任务环境并检查基线，完成后即可启动。');
   requestAnimationFrame(()=>{if(mounted.current)focus(heroRef.current)});
  }catch(e:any){if(mounted.current)setFormError('创建未完成：'+e.message+'。配置已保留，可以重试；不需要重新填写。')}
  finally{actionLock.current=false;if(mounted.current)setBusy('')}
 }
 async function saveLimits(){
  if(actionLock.current)return;actionLock.current=true;setBusy('limits');
  try{
   const changed=await commands.limits(c,limits);
   if(!mounted.current)return;setLimits(null);setNotice(changed?'上限已保存。已启动任务仍受其启动时条件约束；提高额度不自动延长现有进程。':'上限没有变化。');await data.refresh();
  }catch(e:any){if(mounted.current)setLimitsError(e.message)}
  finally{actionLock.current=false;if(mounted.current)setBusy('')}
 }
 const evidence=detail.value?.kind==='evidence'?detail.value.data:null,source=detail.value?.kind==='source'?detail.value.data:null;
 async function readDetail(kind:string,read:(signal:AbortSignal)=>Promise<any>){
  if(actionLock.current)return;
  if(!detail.value)detailTrigger.current=document.activeElement as HTMLElement;
  await act(kind,async()=>{
   const result=await detail.load(async(signal)=>({kind,data:await read(signal)}),{retain:true});
   if(result.error)throw result.error;
  });
 }
 const closeDetails=()=>detail.clear();
 const readEvidence=(id:string,offset=0)=>readDetail('evidence',signal=>api('/evidence/'+id+'?offset='+offset+'&limit=16000',undefined,signal));
 const readSource=(plugin:any,file?:string)=>readDetail('source',async signal=>({...await api('/candidates/'+plugin.candidateId+'/plugins/'+plugin.id+(file?'?file='+encodeURIComponent(file):''),undefined,signal),plugin}));
 const latestReports=c?[...new Map(c.reports.map((r:any)=>[r.batchId||r.kind,r])).values()] as any[]:[];
 const finalReport=latestReports.find((r:any)=>r.kind==='final')||latestReports.find((r:any)=>r.kind==='status_summary');
 return {list:data.list,selected,setSelected,c,view,setView,creating,setCreating,config,setConfig,error,setError,connected:data.connected,busy,events:data.events,
  report:report.value,setReport:report.setValue,reportLoading:report.loading,reportError:report.error?'报告读取失败：'+report.error+'。请重新选择报告重试。':'',
  evidence,setEvidence:(value:any)=>detail.setValue(value?{kind:'evidence',data:value}:null),source,setSource:(value:any)=>detail.setValue(value?{kind:'source',data:value}:null),
  limits,setLimits,notice,setNotice,models:data.models,modelCatalogNote:data.note,settingsOpen,setSettingsOpen,refreshModels:data.refreshModels,renaming,setRenaming,
  formError,setFormError,limitsError,setLimitsError,setNavigation,contentRef,formRef,formErrorRef,heroRef,detailTrigger,focus,navigate,refresh:data.refresh,
  readingTarget,act,command,readReport,createCampaign,saveLimits,closeDetails,readEvidence,readSource,latestReports,finalReport,h0Ready:c?.candidates.some((x:any)=>!x.plugins.length&&x.check.status==='passed')};
}
