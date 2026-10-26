import {api,key} from './transport.mjs';
export function libraryClient(request=api){return {
 page:({query='',offset=0,includeDeleted=false}={},signal)=>request('/plugin-library?'+new URLSearchParams({query,offset,includeDeleted}),undefined,signal),
 detail:(id,file,signal)=>request('/plugin-library/'+encodeURIComponent(id)+(file?'?file='+encodeURIComponent(file):''),undefined,signal),
 previewDelete:(id,scope,signal)=>request('/plugin-library/'+encodeURIComponent(id)+'/deletion?scope='+scope,undefined,signal),
 defaults:signal=>request('/plugin-library/h0/defaults',undefined,signal),
 preview:(selection,signal)=>request('/plugin-library/h0/preview',{selection},signal),
 h0:(id,signal)=>request('/campaigns/'+encodeURIComponent(id)+'/h0',undefined,signal),
 job:(id,signal)=>request('/plugin-library/jobs/'+encodeURIComponent(id),undefined,signal),
};}
// Persist exact writes before sending. Unknown outcomes are retried with the
// original key after refresh; a new intent cannot overwrite a pending operation.
export function libraryWrites(storage,request=api,makeKey=key){
 const slot='phyexp:plugin-library:pending';
 const pending=()=>JSON.parse(storage.getItem(slot)||'null');
 const retry=async()=>{
  const value=pending();if(!value)return null;
  try{const result=await request(value.route,value.body);
   if(result.jobId)storage.setItem('phyexp:plugin-library:job',result.jobId);
   storage.removeItem(slot);return result;
  }catch(error){if([400,401,403,404,409,422].includes(error.status))storage.removeItem(slot);throw error;}
 };
 return {pending,retry,async send(route,body){
  if(pending())throw Error('还有结果未确认的插件库操作，请先核对原请求。');
  storage.setItem(slot,JSON.stringify({route,body:{...body,idempotencyKey:makeKey()}}));return retry();
 }};
}
