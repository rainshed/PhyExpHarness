// Resolve an explicitly supplied, isolated native profile. No network request or secret output.
import fs from 'node:fs';
import crypto from 'node:crypto';
import {Context} from '@deepseek-ai/cordis';
import {LlmRuntime} from '@deepseek-ai/dsh-llm';
import LocalCredentials from '@deepseek-ai/dsh-credentials-local';
import * as DeepSeek from '@deepseek-ai/dsh-llm-deepseek-api-key';
const [profileFile,credentialFile,output]=process.argv.slice(2);
const config=JSON.parse(fs.readFileSync(profileFile));
const ctx=new Context();
try{
 await ctx.plugin(LlmRuntime).await();
 await ctx.plugin(LocalCredentials,{path:credentialFile,watch:false}).await();
 await ctx.plugin(DeepSeek,config).await();
 const bindings=[];
 for(const provider of ctx.llm.listProviders())for(const model of await ctx.llm.listModels(provider.id)){
  const call=await ctx.llm.resolveCallConfig({provider:provider.id,model:model.id});
  const info=await ctx.llm.resolveModelInfo(provider.id,model.id);
  const frozen={adapter:'deepseek-api-key',pluginVersion:'0.2.1-rc.2',config,call,info,credentialRef:config.apiKeyEnv};
  const credential=await ctx.credentials.resolve(config.apiKeyEnv);
  bindings.push({id:'native-'+crypto.createHash('sha256').update(JSON.stringify(frozen)).digest('hex'),provider:provider.id,model:model.id,label:model.name||model.id,frozen,credential:{ref:config.apiKeyEnv,value:credential.value}});
 }
 fs.writeFileSync(output,JSON.stringify({version:'native-reference-catalog-v1',bindings}),{mode:0o600});
 console.log(JSON.stringify({models:bindings.map(b=>b.frozen.call)}));
}finally{await ctx.fiber.dispose();}
