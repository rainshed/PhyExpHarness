import Ajv from 'ajv';
import defaults from './model-catalog.json' with {type:'json'};
import schema from './provider-config.schema.json' with {type:'json'};
const validate=new Ajv({strict:false}).compile(schema);

// Runtime consumes a frozen host snapshot, never the Runner's request or an ambient config file.
export function providerRoute(model, snapshot=model.providerConfig) {
 const route=structuredClone(snapshot??defaults.providers[model.provider]);
 if(!route)throw new Error('Unsupported model provider');
 const config={schemaVersion:1,providers:{[model.provider]:route}};
 if(!validate(config))throw new Error('Invalid provider configuration: '+(validate.errors?.[0]?.instancePath||'/'));
 const auth=route.auth.type;
 if(model.provider==='openai-codex') {
  if(route.adapter!=='pi-ai'||auth!=='codex'||route.api!==undefined||route.baseURL!==undefined||route.preflightURL!=='https://chatgpt.com/backend-api/codex/responses')throw new Error('openai-codex must retain the original Codex subscription route');
 } else {
  if(auth==='codex')throw new Error('Codex authentication is only supported on openai-codex');
  if(!route.baseURL)throw new Error('baseURL is required');
  if(route.adapter==='pi-ai'&&!route.api)throw new Error('An explicit supported api is required');
 }
 if(route.adapter==='deepseek'&&(model.provider!=='deepseek-official'||auth!=='api-key'||route.api!==undefined||route.compat!==undefined||route.transport!==undefined))throw new Error('Invalid native DeepSeek route');
 for(const value of [route.baseURL,route.preflightURL].filter(v=>v!==undefined)) {
  const u=new URL(value);
  if(u.username||u.password||u.search||u.hash||!(u.protocol==='https:'||u.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(u.hostname)))throw new Error('Invalid provider endpoint');
 }
 const ids=new Set();
 for(const m of route.models){
  if(ids.has(m.id))throw new Error('Duplicate model');ids.add(m.id);
  if(m.reasoningEfforts===false?m.defaultReasoningEffort!==undefined:!Object.hasOwn(m.reasoningEfforts,m.defaultReasoningEffort))throw new Error('Invalid model effort default');
  if(m.reasoningEfforts&&Object.entries(m.reasoningEfforts).some(([k,v])=>v===''||v===null&&k!=='off'))throw new Error('Invalid reasoning effort mapping');
  if(route.adapter==='pi-ai'&&m.reasoningEfforts&&Object.keys(m.reasoningEfforts).every(k=>k==='off'))throw new Error('Use false for a non-reasoning model');
  if(route.adapter==='deepseek'&&(m.reasoningEfforts===false||Object.entries(m.reasoningEfforts).some(([k,v])=>!['off','low','high','max'].includes(k)||v!==k)||m.compat))throw new Error('Invalid native DeepSeek reasoning configuration');
 }
 const entry=route.models.find(m=>m.id===model.model);
 if(!entry)throw new Error('Unsupported model configuration');
 if(entry.reasoningEfforts===false?model.reasoningEffort!=null:!Object.hasOwn(entry.reasoningEfforts,model.reasoningEffort))throw new Error('Unsupported model reasoning effort');
 return {...route,models:[entry]};
}

export function piAiProfile(route) {
 return { ...(route.api?{api:route.api}:{}),...(route.baseURL?{baseURL:route.baseURL}:{}),
  ...(route.auth.type==='api-key'?{apiKeyEnv:route.auth.env}:{}),...(route.compat?{compat:route.compat}:{}),
  ...(route.transport?{transport:route.transport}:{}),
  models:route.models.map(({id,name,contextWindow,maxTokens,input,reasoningEfforts,compat})=>({id,...(name?{name}:{}),
   ...(contextWindow?{contextWindow}:{}),...(maxTokens?{maxTokens}:{}),...(input?{input}:{}),reasoningEfforts,...(compat?{compat}:{})})),
  retryPolicy:{mode:'normal',maxRetries:0}};
}
