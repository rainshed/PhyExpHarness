import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {Context} from '@deepseek-ai/cordis';
import {LlmRuntime} from '@deepseek-ai/dsh-llm';
import LocalCredentials from '@deepseek-ai/dsh-credentials-local';
import * as PiAi from '@deepseek-ai/dsh-llm-pi-ai';
import * as DeepSeek from '@deepseek-ai/dsh-llm-deepseek-api-key';
import {createProviderCredentials} from '../host/provider_auth.mjs';
import {providerRuntime} from '../host/model_gateway.mjs';
import {providerRoute,piAiProfile} from '../host/providers.mjs';
import {createChatGPTCredentials} from '../host/chatgpt_auth.mjs';
import {usesCodexHost} from './native_auth.mjs';
export function referenceSpec(){return process.env.PHYEXP_REFERENCE_SPEC?JSON.parse(fs.readFileSync(process.env.PHYEXP_REFERENCE_SPEC)):null;}
export async function referenceProvider(spec){
 if(!spec.native){
  const model=spec.fixedSolver,credentials=createProviderCredentials(model);
  try{return {model,credentials,provider:await providerRuntime({model,credentialFile:credentials.credentialFile}),
   raw:providerRoute(model),wireProfile:piAiProfile(providerRoute(model))};}catch(error){credentials.dispose();throw error;}
 }
 const frozen=spec.native;
 const codexHost=usesCodexHost(frozen);
 let credentials;
 if(codexHost)credentials=createChatGPTCredentials();
 else{
 const secret=JSON.parse(fs.readFileSync(spec.credentialFile));
 if(secret.ref!==frozen.credentialRef||!secret.value)throw new Error('Native credential binding unavailable');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-reference-auth-'));fs.chmodSync(dir,0o700);
 const credentialFile=path.join(dir,'credentials.json');fs.writeFileSync(credentialFile,JSON.stringify({version:1,refs:{[secret.ref]:secret.value},records:{}}),{mode:0o600});
 credentials={credentialFile,description:'Frozen native DeepSeek Harness provider; host-only credential reference',
  redact:value=>[secret.value,JSON.stringify(secret.value).slice(1,-1)].reduce((s,key)=>s.split(key).join('[REDACTED]'),String(value)),dispose:()=>fs.rmSync(dir,{recursive:true,force:true})};
 }
 const ctx=new Context();
 try{
  await ctx.plugin(LlmRuntime).await();await ctx.plugin(LocalCredentials,{path:credentials.credentialFile,watch:false}).await();
  await ctx.plugin(frozen.adapter==='pi-ai'?PiAi:DeepSeek,frozen.config).await();
  const info=await ctx.llm.resolveModelInfo(frozen.call.provider,frozen.call.model);
  const provider={info,stream:request=>ctx.llm.stream(request),dispose:()=>ctx.fiber.dispose()};
  return {model:frozen.call,credentials,provider,wireProfile:frozen.config.providers?.[frozen.call.provider]||frozen.config,
   raw:{adapter:frozen.adapter==='deepseek-api-key'?'deepseek':'pi-ai',...(codexHost?{auth:{type:'codex'}}:{})}};
 }catch(error){credentials.dispose();await ctx.fiber.dispose();throw error;}
}
