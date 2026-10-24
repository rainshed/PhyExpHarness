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
export function budgetGate({deadline,softTokenLimit=Infinity,requestReserve=300000,url,token,purpose='solver',
 accountingTimeoutMs=10000,accountingRetryMs=500}) {
 if(softTokenLimit===null)softTokenLimit=Infinity;
 const active=new Map(),settlements=new Map(),pending=new Map();let confirmed=0,unknown=0;
 async function send(action,data,signal,timeoutMs=accountingTimeoutMs){
  if(!url)return {status:'granted'};
  let response,body;
  try {
   response=await fetch(url+'/'+action,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+token},
    body:JSON.stringify({purpose,...data}),signal:signal?AbortSignal.any([signal,AbortSignal.timeout(timeoutMs)]):AbortSignal.timeout(timeoutMs)});
   // Busy responses from a restarting server/proxy need not have a JSON body.
   if([408,500,502,503,504].includes(response.status)){
    await response.body?.cancel();throw fault('accounting_unavailable',{action,httpStatus:response.status});
   }
   try{body=await response.json();}
   catch(error){
    if(error?.name==='SyntaxError')throw fault('accounting_protocol_error',{action,httpStatus:response.status});
    throw error;
   }
  }catch(error){
   if(error.admissionFailure)throw error;
   // Keep useful facts, never response bodies, URLs, credentials or raw messages.
   throw fault(signal?.aborted?'request_cancelled':'accounting_unavailable',
    {action,transport:error?.name==='TimeoutError'?'timeout':'connection',timeoutMs});
  }
  if(!body||typeof body!=='object')throw fault('accounting_protocol_error',{action,httpStatus:response.status});
  if(action==='reserve'&&response.status===429&&body.status==='waiting'&&ADMISSION_CODES.has(body.code))return body;
  if(!response.ok)throw fault(ADMISSION_CODES.has(body.code)?body.code:'accounting_protocol_error',
   {action,httpStatus:response.status,boundary:body.boundary,observed:body.observed,userLimitsRevision:body.userLimitsRevision,resourcePlanRevision:body.resourcePlanRevision});
  if(action==='reserve'&&body.status!=='granted')throw fault('accounting_protocol_error');
  return body;
 }
 async function available(action,data,{signal,onState}){
  let attempt=0,lastFailure;
  while(true){
   if(signal?.aborted)throw fault('request_cancelled');
   if(Date.now()>=deadline)throw fault('trial_deadline',{lastAccountingFailure:lastFailure});
   try{return await send(action,data,signal,Math.max(1,Math.min(accountingTimeoutMs,deadline-Date.now())));}
   catch(error){
    if(error.code!=='accounting_unavailable')throw error;
    lastFailure=error.admissionFailure;
    const delay=Math.min(2000,accountingRetryMs*2**Math.min(attempt++,3),Math.max(1,deadline-Date.now()));
    onState({status:'waiting',...lastFailure,requestId:data.id,retryAfterMs:delay,attempt});
    await wait(delay,signal);
   }
  }
 }
 return {
  async reserve(id,_request,{signal,onState=()=>{}}={}){
   // A lost settlement response must not strand central reservations forever.
   // Replay receipts only; the provider and tools are never replayed here.
   for(const [requestId,data] of pending){
    await available('settle',data,{signal,onState});pending.delete(requestId);
   }
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
    try {result=await available('reserve',{id,reservedTokens:requestReserve,admissionVersion:1},{signal,onState});}
    catch(error){active.delete(id);throw error;}
    if(result.status==='granted'){onState({status:'granted'});return;}
    active.delete(id);
    if(previous!==result.code){onState(result);previous=result.code;}
    await wait(Math.min(1000,Math.max(1,result.retryAfterMs||500),Math.max(1,deadline-Date.now())),signal);
   }
  },
  async settle(id,result){
   const tokens=result.usage?.totalTokens;
   const data={id,confirmedTokens:Number.isFinite(tokens)?tokens:null,unknown:!result.finish||result.finish.kind==='error'||!Number.isFinite(tokens)};
   if(settlements.has(id)){
    if(JSON.stringify(settlements.get(id))!==JSON.stringify(data))throw fault('accounting_protocol_error',{action:'settle'});
   }else{
    const reserve=active.get(id)||requestReserve;active.delete(id);settlements.set(id,data);
    if(Number.isFinite(tokens))confirmed+=tokens;
    if(data.unknown)unknown+=reserve;
   }
   pending.set(id,data);
   try{await send('settle',data);pending.delete(id);}
   catch(error){
    if(error.code!=='accounting_unavailable')throw error;
    // The gateway has already persisted the receipt. Retry before the next
    // admission, or let the controller reconcile it after the worker exits.
    return {status:'pending',...error.admissionFailure};
   }
  },
  snapshot:()=>({confirmedTokens:confirmed,unknownReservedTokens:unknown,inflightReservedTokens:[...active.values()].reduce((a,b)=>a+b,0),pendingSettlementRequests:pending.size,limitKind:'soft',softTokenLimit:Number.isFinite(softTokenLimit)?softTokenLimit:null}),
 };
}
