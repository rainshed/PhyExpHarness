// Startup watchdogs remain effective without the controller. Admission waiting is not a provider retry.
export const ADMISSION_CODES=new Set(['storage_capacity_wait','budget_admission_denied','budget_inflight_wait','budget_plan_wait',
 'accounting_unavailable','accounting_lease_expired','accounting_auth_failed','accounting_protocol_error',
 'request_cancelled','trial_deadline','campaign_deadline']);
function fault(code,details={}){
 const error=new Error(code==='budget_admission_denied'?'Soft token threshold reached':code==='trial_deadline'?'Deadline reached':code);
 error.admissionFailure={code,...details};error.code=code;return error;
}
async function wait(ms,signal){
 if(signal?.aborted)throw fault('request_cancelled');
 await new Promise((resolve,reject)=>{
  const stop=()=>{clearTimeout(timer);signal?.removeEventListener('abort',stop);reject(fault('request_cancelled'));};
  const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},ms);
  signal?.addEventListener('abort',stop,{once:true});
 });
}
export function budgetGate({deadline,softTokenLimit=Infinity,requestReserve=300000,url,token,purpose='solver'}) {
 if(softTokenLimit===null)softTokenLimit=Infinity;
 const active=new Map();let confirmed=0,unknown=0;
 async function send(action,data,signal){
  if(!url)return {status:'granted'};
  let response,body;
  try {
   response=await fetch(url+'/'+action,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+token},
    body:JSON.stringify({purpose,...data}),signal:signal?AbortSignal.any([signal,AbortSignal.timeout(10000)]):AbortSignal.timeout(10000)});
   body=await response.json();
  }catch(error){throw fault(signal?.aborted?'request_cancelled':'accounting_unavailable');}
  if(action==='reserve'&&response.status===429&&body.status==='waiting'&&ADMISSION_CODES.has(body.code))return body;
  if(!response.ok)throw fault(ADMISSION_CODES.has(body.code)?body.code:'accounting_protocol_error',
   {httpStatus:response.status,boundary:body.boundary,observed:body.observed,userLimitsRevision:body.userLimitsRevision,resourcePlanRevision:body.resourcePlanRevision});
  if(action==='reserve'&&body.status!=='granted')throw fault('accounting_protocol_error');
  return body;
 }
 return {
  async reserve(id,_request,{signal,onState=()=>{}}={}){
   let previous='';
   while(true){
    if(signal?.aborted)throw fault('request_cancelled');
    if(Date.now()>=deadline)throw fault('trial_deadline');
    const committed=confirmed+unknown;
    if(committed+requestReserve>softTokenLimit)throw fault('budget_admission_denied',{boundary:'worker_startup_limit'});
    if(committed+[...active.values()].reduce((a,b)=>a+b,0)+requestReserve>softTokenLimit){
     if(previous!=='local'){onState({status:'waiting',code:'budget_inflight_wait',boundary:'worker_inflight'});previous='local';}
     await wait(Math.min(500,Math.max(1,deadline-Date.now())),signal);continue;
    }
    // Claim the local reservation before awaiting the central ledger.
    active.set(id,requestReserve);
    let result;
    try {result=await send('reserve',{id,reservedTokens:requestReserve,admissionVersion:1},signal);}
    catch(error){active.delete(id);throw error;}
    if(result.status==='granted'){onState({status:'granted'});return;}
    active.delete(id);
    if(previous!==result.code){onState(result);previous=result.code;}
    await wait(Math.min(1000,Math.max(1,result.retryAfterMs||500),Math.max(1,deadline-Date.now())),signal);
   }
  },
  async settle(id,result){
   const reserve=active.get(id)||requestReserve;active.delete(id);
   const tokens=result.usage?.totalTokens;
   if(Number.isFinite(tokens))confirmed+=tokens;
   if(!result.finish||result.finish.kind==='error'||!Number.isFinite(tokens))unknown+=reserve;
   await send('settle',{id,confirmedTokens:Number.isFinite(tokens)?tokens:null,unknown:!result.finish||result.finish.kind==='error'||!Number.isFinite(tokens)});
  },
  snapshot:()=>({confirmedTokens:confirmed,unknownReservedTokens:unknown,inflightReservedTokens:[...active.values()].reduce((a,b)=>a+b,0),limitKind:'soft',softTokenLimit:Number.isFinite(softTokenLimit)?softTokenLimit:null}),
 };
}
