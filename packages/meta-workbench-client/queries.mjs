import {api} from './transport.mjs';
import {readModelCatalog} from './model-catalog.mjs';

// A subscription owns only reads. Disposing never sends a backend command.
export function watchCampaign({id='',request=api,onData,onError,interval=2000}){
 const controller=new AbortController();let live=true,pending=null,cursor=0,events=[],catalogRevision;
 const refresh=()=>{
  if(!live)return Promise.resolve();if(pending)return pending;
  pending=(async()=>{
   try{
    const [list,catalog]=await Promise.all([request('/campaigns',undefined,controller.signal),request('/models',undefined,controller.signal)]);
    if(!live)return;
    const selectionMissing=!!id&&!list.some(item=>item.id===id);
    let campaign=null,newEvents=[];
    if(id&&!selectionMissing)[campaign,newEvents]=await Promise.all([
     request('/campaigns/'+id,undefined,controller.signal),request('/campaigns/'+id+'/events?after='+cursor,undefined,controller.signal)]);
    if(!live)return;
    if(newEvents.length){cursor=newEvents.at(-1).seq;events=[...events,...newEvents].slice(-100);}
    const update={list,campaign,events,selectionMissing};
    if(catalog.revision==null||catalogRevision==null||catalog.revision>=catalogRevision){
     Object.assign(update,readModelCatalog(catalog),{catalogRevision:catalog.revision});catalogRevision=catalog.revision;
    }
    onData(update);
   }catch(error){if(live)onError(error);}
   finally{pending=null;}
  })();return pending;
 };
 const timer=setInterval(refresh,interval);refresh();
 return {refresh,dispose(){live=false;controller.abort();clearInterval(timer);}};
}
