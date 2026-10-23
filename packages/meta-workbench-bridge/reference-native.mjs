import {resolveAdapterOptions} from '@deepseek-ai/dsh-llm-deepseek-api-key';
import {launchEnvironmentOf} from '@deepseek-ai/dsh-launch-environment';
// Trusted host bridge: this document never goes to a browser. Use the native
// directory/settings/credential services; do not maintain a second model catalog.
import crypto from 'node:crypto';
const hash=value=>crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
export async function captureNativeModels(ctx){
 const llm=ctx.get('llm'),settings=ctx.get('settings'),credentials=ctx.get('credentials');
 if(!llm||!settings)throw new Error('DeepSeek Harness native model/settings services unavailable');
 const descriptions=await settings.describe({redactSecrets:false});
 const entries=[...(ctx.loader?.entries?.()||[])];
 const plugins=new Map(entries.map(entry=>[entry.options.id,entry.options.name]));
 const directory=llm.listConfigurableProviders();const bindings=[];
 for(const provider of llm.listProviders()){
  const route=directory.find(d=>d.provider===provider.id);
  if(!route)continue;
  const description=descriptions.find(d=>d.ns===route.settingsNs);
  const plugin=plugins.get(route.settingsNs)||route.settingsNs;
  const adapter=String(plugin).includes('llm-pi-ai')?'pi-ai':String(plugin).includes('llm-deepseek-api-key')?'deepseek-api-key':null;
  if(!adapter||!description)continue;
  let profile=description.value;
  for(const key of route.settingsPath)profile=profile?.[key];
  if(!profile)continue;
  // Freeze effective settings, including defaults resolved by the native adapter.
  const raw=structuredClone(profile);
  if(adapter==='deepseek-api-key')raw.baseURL=resolveAdapterOptions(raw,launchEnvironmentOf(ctx)).baseURL;
  const ref=raw.apiKeyEnv||(adapter==='deepseek-api-key'?'DEEPSEEK_API_KEY':null);
  const credential=ref&&credentials?await credentials.resolve(ref):null;
  const models=await llm.listModels(provider.id);
  for(const model of models){
   const call=await llm.resolveCallConfig({provider:provider.id,model:model.id});
   const info=await llm.resolveModelInfo(provider.id,model.id);
   const config=adapter==='pi-ai'?{providers:{[provider.id]:raw}}:raw;
   const frozen={adapter,pluginVersion:'0.2.1-rc.2',config,call,info,credentialRef:ref};
   const id='native-'+hash(frozen);
   bindings.push({id,label:model.name||model.id,provider:provider.id,model:model.id,
    frozen,credential:credential?{ref,value:credential.value}:null,
    unavailable:ref&&!credential?'Native credential is unavailable':!ref?'Native authentication requires a dedicated adapter':null});
  }
 }
 return {version:'native-reference-catalog-v1',bindings};
}
