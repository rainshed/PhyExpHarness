import {DEFAULT_STREAM_POLICY} from '../host/stream_guard.mjs';
// Protocol-preserving host gateway. No credentials or upstream addresses enter a Runner.
import fs from 'node:fs';
import crypto from 'node:crypto';
import {ADMISSION_CODES} from '../host/budget.mjs';
import {classifyModelFailure} from '../host/model_failures.mjs';
export function wireBinding(runtime,harness){
 const profile=runtime.wireProfile,model=runtime.model;
 const doc=JSON.parse(fs.readFileSync(runtime.credentials.credentialFile));
 if(runtime.raw.auth?.type==='codex'){
  if(harness!=='codex'||model.provider!=='openai-codex')throw new Error('Codex subscription must retain its native provider and Harness');
  const token=doc.records?.['llm-pi-ai/openai-codex']?.payload?.access;
  const claims=JSON.parse(Buffer.from(token?.split('.')[1]||'','base64url').toString());
  const account=claims['https://api.openai.com/auth']?.chatgpt_account_id;
  if(!account||!Number.isFinite(claims.exp)||claims.exp*1000<=Date.now())throw new Error('Codex subscription binding is unavailable or expired');
  return {model,protocol:'responses',codexSubscription:true,baseURL:'https://chatgpt.com/backend-api/codex',
   headers:{authorization:'Bearer '+token,'chatgpt-account-id':account,originator:'codex_cli_rs','OpenAI-Beta':'responses=experimental',accept:'text/event-stream'}};
 }
 const deepseek=runtime.raw.adapter==='deepseek';
 const protocol=deepseek?'anthropic':profile.api==='anthropic-messages'?'anthropic':profile.api==='openai-responses'?'responses':null;
 if(protocol!==(harness==='codex'?'responses':'anthropic'))throw new Error('Reference protocol is incompatible');
 const secret=doc.refs[profile.apiKeyEnv||runtime.raw.auth?.env];
 if(!secret)throw new Error('Explicit API-key credential required for this reference adapter');
 const baseURL=profile.baseURL||runtime.raw.baseURL||(deepseek?'https://api.deepseek.com/anthropic':null);
 if(!baseURL)throw new Error('Explicit native provider URL required');
 const url=new URL(baseURL);
 if(!['https:','http:'].includes(url.protocol)||url.username||url.password||url.search||url.hash)throw new Error('Invalid upstream URL');
 return {model,protocol,deepseek,baseURL:baseURL.replace(/\/+$/,''),headers:{...(profile.headers||{}),...(protocol==='anthropic'?{'x-api-key':secret,'anthropic-version':'2023-06-01'}:{authorization:'Bearer '+secret})}};
}
export function fixedRequest(binding,payload){
 if(payload.method!=='POST')throw new Error('Only model POST requests are permitted');
 const route=payload.path.split('?')[0];
 const allowed=binding.protocol==='responses'?['/responses','/responses/compact']:['/v1/messages','/v1/messages/count_tokens'];
 if(!allowed.includes(route))throw new Error('Reference model endpoint not allowed');
 const body=JSON.parse(payload.body);
 if(body.model!==binding.model.model)throw new Error('Reference model mismatch; auxiliary/fallback models must use the same binding');
 const cap=binding.model.maxTokens;
 const effort=binding.model.reasoningEffort;
 if(binding.protocol==='responses'){
  if(binding.codexSubscription){body.store=false;delete body.max_output_tokens;}
  if(!route.endsWith('/compact')){
   if(cap!==undefined&&!binding.codexSubscription)body.max_output_tokens=cap;
   if(effort!==undefined)body.reasoning={...body.reasoning,effort};
  }
 }else if(!route.endsWith('/count_tokens')){
  if(cap!==undefined)body.max_tokens=cap;
  if(binding.deepseek){
   body.thinking={type:effort==='off'?'disabled':'enabled'};
   if(effort==='off')delete body.output_config;else body.output_config={effort:effort||'high'};
  }else{
   if(effort===undefined||effort==='off'){body.thinking={type:'disabled'};delete body.output_config;}
   else{body.thinking={type:'adaptive'};body.output_config={...body.output_config,effort};}
  }
 }
 // Preserve the provider-native message/tool/reasoning history byte-for-byte as JSON values.
 return {route,body};
}
export class WireGateway{
 constructor({binding,budget,deadline,audit,redact=String,fetchImpl=fetch,policy=DEFAULT_STREAM_POLICY}){Object.assign(this,{binding,budget,deadline,audit,redact,fetchImpl,policy});this.active=new Set();this.stopped=false;}
 record(row){fs.appendFileSync(this.audit,this.redact(JSON.stringify({time:new Date().toISOString(),...row}))+'\n');}
 fail(code,id,stage,observed={}){const failure={schemaVersion:1,code,requestId:id,stage,source:'reference-model-gateway',detectedAt:new Date().toISOString(),observed};this.failure??=failure;this.record({type:'failure',...failure});}
 abort(){this.stopped=true;for(const ctl of this.active)ctl.abort();}
 async *stream(payload,signal){
  if(this.stopped||Date.now()>=this.deadline)throw new Error('Reference deadline reached');
  const {route,body}=fixedRequest(this.binding,payload),id='reference-request-'+crypto.randomUUID();
  const ctl=new AbortController();this.active.add(ctl);
  const bound=AbortSignal.any([ctl.signal,signal||new AbortController().signal,AbortSignal.timeout(Math.max(1,Math.min(this.policy.requestTimeoutMs??Infinity,this.deadline-Date.now())))]);
  let idle;const resetIdle=()=>{clearTimeout(idle);if(this.policy.streamIdleTimeoutMs!=null)idle=setTimeout(()=>ctl.abort('Reference stream idle timeout'),this.policy.streamIdleTimeoutMs);};resetIdle();
  let reserved=false,usage={},finished=false,buffer='',jsonBody='',sse=false;const identities=new Set();
  const observe=row=>{
   const u=row.response?.usage||row.message?.usage||row.usage;
   if(u)usage={...usage,...u};
   if(row.type==='response.completed'||row.type==='response.done')finished=row.response?.status!=='incomplete'&&!row.response?.error;
   if(row.type==='message_stop')finished=true;
   const actual=row.response?.model||row.message?.model||row.model;
   if(actual&&!identities.has(actual)){identities.add(actual);this.record({type:'server_model_identity',id,requested:this.binding.model.model,actual});}
  };
  const observeLine=line=>{
   line=line.trim();
   if(line.startsWith('data:')){sse=true;const data=line.slice(5).trim();if(data!=='[DONE]'){try{observe(JSON.parse(data));}catch{}}}
  };
  try{
   await this.budget.reserve(id,body,{signal:bound});reserved=true;
   this.record({type:'admitted',id,model:this.binding.model,endpoint:route});
   const root=this.binding.baseURL;
   const url=root+(root.endsWith('/v1')&&route.startsWith('/v1/')?route.slice(3):route);
   const response=await this.fetchImpl(url,{method:'POST',headers:{...this.binding.headers,'content-type':'application/json',...(payload.headers?.['anthropic-beta']?{'anthropic-beta':payload.headers['anthropic-beta']}:{})},body:JSON.stringify(body),signal:bound,redirect:'error'});
   const type=response.headers.get('content-type')||'application/json';
   yield {status:response.status,headers:{'content-type':type}};
   const decoder=new TextDecoder();let size=0;
   for await(const bytes of response.body){
    resetIdle();
    size+=bytes.length;if(size>32*1024*1024)throw new Error('Oversized reference response');
    const text=decoder.decode(bytes,{stream:true});buffer+=text;
    if(!type.includes('event-stream')&&!sse)jsonBody+=text;
    let end;while((end=buffer.indexOf('\n'))>=0){observeLine(buffer.slice(0,end));buffer=buffer.slice(end+1);}
    yield {bytes:Buffer.from(bytes).toString('base64')};
   }
   const tail=decoder.decode();buffer+=tail;observeLine(buffer);
   if(!sse){try{const data=JSON.parse(jsonBody+tail);observe(data);finished=response.ok&&!data.error;}catch{}}
   if(route.endsWith('/count_tokens')&&response.ok){usage={total_tokens:0,input_tokens:0,output_tokens:0};finished=true;}
   if(!response.ok){finished=false;this.fail(classifyModelFailure({status:response.status}).code,id,'model',{httpStatus:response.status});}
   else if(!finished)this.fail('model_stream_incomplete',id,'model');
  }catch(error){
   const code=error.admissionFailure?.code||error.code;
   this.fail(ADMISSION_CODES.has(code)?code:Date.now()>=this.deadline?'trial_deadline':bound.aborted?'request_cancelled':classifyModelFailure(error).code,id,reserved?'model':'admission',error.admissionFailure||{});
   throw error;
  }finally{
   clearTimeout(idle);this.active.delete(ctl);
   if(reserved){
    const input=usage.input_tokens,output=usage.output_tokens;
    const total=usage.total_tokens??(Number.isFinite(input)&&Number.isFinite(output)?input+output+(usage.cache_read_input_tokens||0)+(usage.cache_creation_input_tokens||0):null);
    const cacheRead=usage.cache_read_input_tokens??usage.input_tokens_details?.cached_tokens??0;
    const result={finish:finished?{kind:'completed'}:{kind:'error'},usage:total===null?null:{totalTokens:total,inputTokens:this.binding.protocol==='responses'&&Number.isFinite(input)?input-cacheRead:input,outputTokens:output,cacheReadTokens:cacheRead,cacheWriteTokens:usage.cache_creation_input_tokens||0}};
    this.record({type:'settled',id,...result});await this.budget.settle(id,result);
   }
  }
 }
}
