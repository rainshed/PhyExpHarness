import {useEffect,useRef,useState} from 'react';
import {watchCampaign} from './queries.mjs';
import {LatestRequest,api} from './transport.mjs';
import {readModelCatalog} from './model-catalog.mjs';

export function useCampaignData(selected:string){
 const [data,setData]=useState<any>({list:[],campaign:null,events:[],models:[],note:'',catalogRevision:undefined,selectionMissing:false});
 const [connected,setConnected]=useState(false),[error,setError]=useState('');
 const current=useRef<any>(null),catalogRequest=useRef(new LatestRequest());
 useEffect(()=>{
  setData((old:any)=>({...old,campaign:null,events:[],selectionMissing:false}));
  const subscription=watchCampaign({id:selected,onData:(next:any)=>{
   setData((old:any)=>{
    if(next.catalogRevision!=null&&old.catalogRevision!=null&&next.catalogRevision<old.catalogRevision){
     const {models,note,catalogRevision,...rest}=next;return {...old,...rest};
    }
    return {...old,...next};
   });setConnected(true);
  },onError:(e:Error)=>{setConnected(false);setError(e.message)}});
  current.current=subscription;
  return()=>{subscription.dispose();current.current=null;catalogRequest.current.cancel()};
 },[selected]);
 const refresh=()=>current.current?.refresh();
 const refreshModels=async()=>{
  const result=await catalogRequest.current.run((signal:AbortSignal)=>api('/models',undefined,signal));
  if(!result.current)return;
  const catalog=result.value,parsed=readModelCatalog(catalog);
  setData((old:any)=>catalog.revision!=null&&old.catalogRevision!=null&&catalog.revision<old.catalogRevision?old:{...old,...parsed,catalogRevision:catalog.revision});
 };
 return {...data,connected,error,setError,refresh,refreshModels};
}

export function useResource(scope:string){
 const [value,setValue]=useState<any>(null),[loading,setLoading]=useState(false),[error,setError]=useState('');
 const request=useRef(new LatestRequest());
 const clear=()=>{request.current.cancel();setValue(null);setLoading(false);setError('')};
 useEffect(()=>{clear();return()=>request.current.cancel()},[scope]);
 const load=async(read:(signal:AbortSignal)=>Promise<any>,{retain=false}={})=>{
  if(!retain)setValue(null);setLoading(true);setError('');
  try{const result=await request.current.run(read);if(result.current){setValue(result.value);setLoading(false)}return result;}
  catch(e:any){setError(e.message);setLoading(false);return {current:true,error:e};}
 };
 return {value,setValue,loading,error,load,clear};
}
