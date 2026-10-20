// Safe provider facts for the native request-error extension. Raw messages stay in audit.
export function classifyModelFailure(value={}) {
 const raw=value?.failure||value||{};const message=String(raw.message||'');
 const status=Number.isInteger(raw.status)&&raw.status>=100&&raw.status<=599?raw.status:undefined;
 const knownCodes=new Set(['TRANSPORT','SERVER','RATE_LIMIT','TIMEOUT','EMPTY_RESPONSE','CONTEXT_WINDOW_EXCEEDED','INVALID_CREDENTIAL','AUTHENTICATION','PI_AI_ERROR']);
 let code='model_response_error',providerCode=knownCodes.has(raw.code)?raw.code:'PROVIDER';
 if(raw.code==='TRANSPORT'||/websocket (?:error|closed(?:\s|$)|connection (?:failed|timed out))|fetch failed|connection (?:reset|closed|lost)|socket hang up|disconnect|ECONNRESET|ECONNREFUSED|ETIMEDOUT/i.test(message)){
  code='model_transport_error';providerCode='TRANSPORT';
 }else if(status===503||/servers? (?:are |is )?(?:currently )?overloaded|server_overloaded|overloaded_error/i.test(message)){
  code='model_service_overloaded';providerCode='SERVER';
 }
 const safeMessage=code==='model_transport_error'?'Model connection interrupted':code==='model_service_overloaded'?'Model service overloaded':'Model provider returned an error';
 const failure={code:providerCode,message:safeMessage};
 if(status!==undefined)failure.status=status;
 if(Number.isFinite(raw.providerRetryAfterMs)&&raw.providerRetryAfterMs>0)failure.providerRetryAfterMs=raw.providerRetryAfterMs;
 // Only known diagnostic metadata is projected; never arbitrary provider strings.
 const observed=raw.code==='CONTEXT_WINDOW_EXCEEDED'?{providerCode:raw.code}:{};
 return {code,failure,observed};
}

export const RECOVERABLE_REQUEST_FAILURES=new Set(['model_service_overloaded','model_transport_error','model_stream_incomplete']);
