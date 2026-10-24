export const API='/phyexp/api';
export const key=()=>crypto.randomUUID();
export function createRequest({base=API,fetch:fetcher=(...args)=>globalThis.fetch(...args)}={}){
 return async function request(route,body,signal){
  const response=await fetcher(base+route,{signal,method:body===undefined?'GET':'POST',
   headers:body===undefined?undefined:{'content-type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const value=await response.json();
  if(!response.ok)throw Error(value.error||`请求未完成（${response.status}）`);
  return value;
 };
}
export const api=createRequest();

// Cancel and invalidate independently: a transport may still resolve after abort.
export class LatestRequest {
 generation=0; controller=null;
 cancel(){this.generation++;this.controller?.abort();this.controller=null;}
 async run(read,{timeoutMs=0,timeoutMessage='读取超时，请重试。'}={}){
  this.cancel();const generation=this.generation,controller=new AbortController();this.controller=controller;
  let timer,onAbort;
  const cancelled=new Promise((resolve,reject)=>{
   onAbort=()=>reject(controller.signal.reason);controller.signal.addEventListener('abort',onAbort,{once:true});
   if(timeoutMs>0)timer=setTimeout(()=>controller.abort(new Error(timeoutMessage)),timeoutMs);
  });
  try{const value=await Promise.race([read(controller.signal),cancelled]);return generation===this.generation?{current:true,value}:{current:false};}
  catch(error){if(generation!==this.generation)return {current:false};throw error;}
  finally{clearTimeout(timer);controller.signal.removeEventListener('abort',onAbort);if(this.controller===controller)this.controller=null;}
 }
}
