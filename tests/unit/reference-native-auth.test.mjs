import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {captureNativeModels} from '../../packages/meta-workbench-bridge/reference-native.mjs';
import {referenceProvider} from '../../src/execution/reference/native.mjs';
import {usesCodexHost} from '../../src/execution/reference/native_auth.mjs';
import {wireBinding} from '../../src/execution/reference/wire.mjs';

const profile={models:[{id:'gpt-6-sol',reasoningEfforts:{medium:'medium'}}],reasoning:'medium',transport:'sse',retryPolicy:{mode:'normal',maxRetries:0}};
function nativeContext(raw=profile){
 const llm={listProviders:()=>[{id:'openai-codex'}],listConfigurableProviders:()=>[{provider:'openai-codex',settingsNs:'llm-pi-ai',settingsPath:['providers','openai-codex']}],
  listModels:async()=>[{id:'gpt-6-sol'}],resolveCallConfig:async call=>({...call,reasoningEffort:'medium'}),resolveModelInfo:async()=>({id:'gpt-6-sol'})};
 return {get:name=>({llm,settings:{describe:async()=>[{ns:'llm-pi-ai',value:{providers:{'openai-codex':raw}}}]}}[name])};
}
async function withLogin(run){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'reference-native-auth-')),old=process.env.PHYEXP_CODEX_AUTH_FILE;
 const authFile=path.join(dir,'auth.json');process.env.PHYEXP_CODEX_AUTH_FILE=authFile;
 const write=(suffix='first',exp=Date.now()/1000+3600)=>{
  const token='header.'+Buffer.from(JSON.stringify({exp,'https://api.openai.com/auth':{chatgpt_account_id:'fixture-account'}})).toString('base64url')+'.'+suffix;
  fs.writeFileSync(authFile,JSON.stringify({auth_mode:'chatgpt',tokens:{access_token:token,refresh_token:'never-copy-refresh'}}),{mode:0o600});return token;
 };
 try{await run({write,authFile});}finally{if(old===undefined)delete process.env.PHYEXP_CODEX_AUTH_FILE;else process.env.PHYEXP_CODEX_AUTH_FILE=old;fs.rmSync(dir,{recursive:true,force:true});}
}
test('native Codex capture freezes a host handle and resolves fresh access-only credentials at execution',async()=>withLogin(async({write,authFile})=>{
 const first=write(),captured=await captureNativeModels(nativeContext()),row=captured.bindings[0];
 assert.equal(row.unavailable,null);assert.equal(row.frozen.nativeAuth,'codex-host');assert.equal(row.credential,null);
 assert.ok(!JSON.stringify(captured).includes(first));assert.ok(!JSON.stringify(captured).includes(authFile));
 const fresh=write('rotated'),original=fs.readFileSync(authFile,'utf8');
 const runtime=await referenceProvider({native:row.frozen});
 const temporary=runtime.credentials.credentialFile;
 try{
  assert.equal(runtime.model.reasoningEffort,'medium');assert.equal(runtime.provider.info.id,'gpt-6-sol');
  const doc=JSON.parse(fs.readFileSync(temporary)),grant=doc.records['llm-pi-ai/openai-codex'].payload;
  assert.equal(grant.access,fresh);assert.equal(grant.refresh,'');assert.ok(!JSON.stringify(doc).includes('never-copy-refresh'));
  assert.equal(wireBinding(runtime,'codex').headers.authorization,'Bearer '+fresh);
  assert.throws(()=>wireBinding(runtime,'claude-code'),/retain/);
  assert.equal(runtime.credentials.redact(fresh),'[REDACTED]');
  assert.equal(fs.readFileSync(authFile,'utf8'),original);
 }finally{await runtime.provider.dispose();runtime.credentials.dispose();}
 assert.equal(fs.existsSync(temporary),false);
}));
test('missing or expired Codex login is unavailable without silently changing authentication',async()=>withLogin(async({write})=>{
 assert.match((await captureNativeModels(nativeContext())).bindings[0].unavailable,/Codex/);
 write('expired',Date.now()/1000-1);
 const row=(await captureNativeModels(nativeContext())).bindings[0];
 assert.match(row.unavailable,/过期/);
 await assert.rejects(referenceProvider({native:row.frozen}),/expires/);
}));
test('Codex host credentials cannot be redirected by a native profile',async()=>withLogin(async({write})=>{
 write();const row=(await captureNativeModels(nativeContext())).bindings[0];
 for(const override of [{baseURL:'https://other.test'},{api:'openai-responses'},{headers:{authorization:'other'}},{apiKeyEnv:'OTHER_KEY'}]){
  const frozen=structuredClone(row.frozen);Object.assign(frozen.config.providers['openai-codex'],override);
  assert.throws(()=>usesCodexHost(frozen),/Invalid/);
  await assert.rejects(referenceProvider({native:frozen}),/Invalid/);
  const captured=(await captureNativeModels(nativeContext({...profile,...override}))).bindings[0];
  assert.equal(captured.frozen.nativeAuth,undefined);assert.ok(captured.unavailable);
 }
 const frozen=structuredClone(row.frozen);frozen.config.providers.other={};assert.throws(()=>usesCodexHost(frozen),/Invalid/);
}));
