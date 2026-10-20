// No credentials/provider: load the actual frozen plugin combination in its isolated native SDK.
import fs from 'node:fs';
import path from 'node:path';
import {isolatedSession} from '../host/isolation.mjs';
import {ModelGateway} from '../host/model_gateway.mjs';
import {providerRoute} from '../host/providers.mjs';
const [root,logs]=process.argv.slice(2);
const bundle=JSON.parse(fs.readFileSync(path.join(root,'bundle.json')));
const recipe=JSON.parse(fs.readFileSync(path.join(root,'recipe.json')));
// The response is synthetic, but native session validation must use the frozen model's capabilities.
// Resolving this route is local and does not load credentials or contact the provider.
const entry=providerRoute(recipe).models[0];
const modelInfo={provider:recipe.provider,id:entry.id,name:entry.name??entry.id,
 context:{contextWindow:entry.contextWindow??272000},
 ...(entry.reasoningEfforts?{reasoning:{efforts:Object.keys(entry.reasoningEfforts).map(id=>({id,name:id}))}}:{})};
let receipt;let calls=0;
const gateway=new ModelGateway({model:recipe,deadline:Date.now()+20000,audit:path.join(logs,'check-gateway.jsonl'),adapter:{async *stream(){
 calls++;yield {type:'block-start',index:0,blockType:'text'};yield {type:'block-end',index:0,block:{type:'text',text:'Technical assembly check.'}};
 yield {type:'usage',usage:{inputTokens:1,outputTokens:1,totalTokens:2}};yield {type:'finish',reason:{kind:'stop'}};
}}});
const session=isolatedSession({executionRoot:path.join(root,'src/execution'),logs,gateway,image:bundle.runnerImage,
 config:{disableLocalTools:true,modelInfo,fixedModel:Object.fromEntries(['provider','model','reasoningEffort','maxTokens'].map(k=>[k,recipe[k]])),
 plugins:[{id:'container-tools',name:'/opt/phyexp/src/execution/adapters/quantum_harbor/container_tool.mjs'},
 ...bundle.plugins.map(p=>({id:p.name,name:'/opt/phyexp/'+p.entry,config:p.config}))]},
 mounts:bundle.plugins.length?[`type=bind,source=${path.join(root,'plugins')},target=/opt/phyexp/plugins,readonly`]:[],
 async *handler(op,payload){if(op!=='receipt')throw new Error('Check has no task capabilities');receipt=payload;yield {ok:true};}
});
try{
 await session.request('initialize',{provider:recipe.provider,model:recipe.model,reasoningEffort:recipe.reasoningEffort,maxTokens:recipe.maxTokens,cwd:'/tmp/work'});
 const events=await session.prompt('assembly','Technical assembly check.',15000);
 for(const tool of bundle.plugins.flatMap(p=>p.tools))if(!receipt.tools.includes(tool))throw new Error('Declared tool missing: '+tool);
 if(calls!==1)throw new Error('Unexpected extra call in assembly check');
 await session.shutdown();
 fs.writeFileSync(path.join(logs,'assembly.json'),JSON.stringify({status:'passed',model:'controlled-fake-provider',bundleId:bundle.id,receipt,
  workerSource:import.meta.url,events:events.length},null,2));
 console.log(JSON.stringify({status:'passed',bundleId:bundle.id,model:'controlled-fake-provider'}));
}finally{await session.dispose();}
