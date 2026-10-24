// Only run authority, cancellation, deadline and storage availability gate new calls.
// The accounting adapter is used solely by pre-existing frozen activities.
import {budgetGate} from './budget.mjs';
export const ACCESS_CODES = new Set(['storage_capacity_wait','control_unavailable','request_auth_failed',
 'request_lease_expired','control_protocol_error','request_cancelled','trial_deadline','campaign_deadline']);
function fault(code,details={}) {
 const error=new Error(code);error.code=code;error.admissionFailure={code,...details};return error;
}
function wait(ms,signal) {
 return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(fault('request_cancelled'));return;}
  const stop=()=>{clearTimeout(timer);reject(fault('request_cancelled'));};
  const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},ms);
  signal?.addEventListener('abort',stop,{once:true});
 });
}
export function modelAccess({deadline,url,token,timeoutMs=10000,retryMs=500,fetchImpl=fetch}) {
 if(!Number.isFinite(deadline))throw Error('Explicit finite deadline required');
 return {
  async reserve(_id,request,{signal,onState=()=>{}}={}) {
   while(true) {
    if(signal?.aborted)throw fault('request_cancelled');
    if(Date.now()>=deadline)throw fault('trial_deadline');
    // Standalone runs have no controller; their local deadline and watchdog apply.
    if(!url)return;
    let result;
    try {
     const response=await fetchImpl(url,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+token},
      body:JSON.stringify({agentId:request?.sessionId}),
      signal:AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(Math.max(1,Math.min(timeoutMs,deadline-Date.now())))])});
     if([408,500,502,503,504].includes(response.status)){await response.body?.cancel();throw fault('control_unavailable');}
     try{result=await response.json();}catch{throw fault('control_protocol_error');}
     if(response.ok&&result?.status==='granted')return;
     if(!result||!ACCESS_CODES.has(result.code))throw fault('control_protocol_error');
     if(response.status!==429||result.status!=='waiting'||result.code!=='storage_capacity_wait')throw fault(result.code);
    } catch(error) {
     if(signal?.aborted)throw fault('request_cancelled');
     if(error.admissionFailure&&error.code!=='control_unavailable')throw error;
     result={status:'waiting',code:'control_unavailable'};
    }
    onState(result);
    await wait(Math.min(retryMs,Math.max(1,deadline-Date.now())),signal);
   }
  },
 };
}
export function executionAccess(deadline,env=process.env) {
 if(!env.PHYEXP_MODEL_ACCESS_URL&&env.PHYEXP_ACCOUNTING_URL)return budgetGate({deadline,softTokenLimit:Number(env.PHYEXP_RUN_TOKEN_LIMIT)||Infinity,
  url:env.PHYEXP_ACCOUNTING_URL,token:env.PHYEXP_ACCOUNTING_TOKEN,purpose:'solver'});
 return modelAccess({deadline,url:env.PHYEXP_MODEL_ACCESS_URL,token:env.PHYEXP_MODEL_ACCESS_TOKEN});
}
