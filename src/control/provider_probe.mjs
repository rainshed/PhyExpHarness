// A bounded diagnostic through the production credential bridge, adapter and stream guard.
// Only the fixed echo below is executed. No model-generated tools or activity state are used.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createProviderCredentials} from '../execution/host/provider_auth.mjs';
import {ModelGateway,providerRuntime} from '../execution/host/model_gateway.mjs';

export async function probeProvider({model,providerConfig}) {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-provider-test-'));
 fs.chmodSync(dir,0o700);
 const started=Date.now(),deadline=started+45000;
 const selected={...model,maxTokens:Math.min(512,providerConfig.models[0].maxTokens??8192)};
 let credentials,runtime,gateway,requests=0;
 const checks={response:false,stream:false,toolCall:false,toolResult:false};
 let error='';
 try {
  credentials=createProviderCredentials(selected,{providerConfig,minimumValidityMs:120000});
  runtime=await providerRuntime({model:selected,providerConfig,credentialFile:credentials.credentialFile});
  gateway=new ModelGateway({model:selected,adapter:runtime,deadline,audit:path.join(dir,'audit.jsonl'),redact:credentials.redact,
   policy:{requestTimeoutMs:25000,streamIdleTimeoutMs:15000,maxResponseBytes:65536,maxToolArgumentBytes:4096,cleanupGraceMs:1000},
   reserve:async()=>{if(++requests>2)throw Error('测试最多允许两次请求');}});
  const request={...selected,messages:[{role:'user',content:[{type:'text',text:'Connection test. Call phyexp_connection_check exactly once with value "connection-ok". After receiving the tool result, reply with exactly PHYEXP_OK. Do not call other tools.'}]}],
   tools:[{name:'phyexp_connection_check',description:'Return a fixed connection-test value; no external action.',parameters:{type:'object',properties:{value:{type:'string',enum:['connection-ok']}},required:['value'],additionalProperties:false}}]};
  async function turn(input) {
   const blocks=[];let finish;
   for await(const chunk of gateway.stream(input)){
    if(['text-delta','reasoning-delta','tool-call-delta'].includes(chunk.type))checks.stream=true;
    if(chunk.type==='block-end')blocks.push(chunk.block);
    if(chunk.type==='finish')finish=chunk;
   }
   checks.response=!!finish&&finish.reason.kind!=='error';
   if(gateway.firstFailure)throw Error(gateway.firstFailure.code);
   return {blocks,finish};
  }
  const first=await turn(request);
  const calls=first.blocks.filter(b=>b.type==='tool-call');
  if(calls.length!==1||calls[0].name!=='phyexp_connection_check')throw Error('收到模型响应，但未返回约定的测试工具调用。');
  let args;try{args=JSON.parse(calls[0].arguments)}catch{throw Error('工具调用参数不是有效 JSON。')}
  if(args?.value!=='connection-ok'||Object.keys(args).length!==1)throw Error('测试工具参数与约定不符。');
  checks.toolCall=true;
  const second=await turn({...request,messages:[...request.messages,
   {role:'assistant',content:first.blocks,source:{provider:model.provider,model:model.model,replayState:first.finish.replayState}},
   {role:'tool',toolCallId:calls[0].id,content:[{type:'text',text:'connection-ok'}]}]});
  checks.toolResult=second.blocks.filter(b=>b.type==='text').map(b=>b.text).join('').trim()==='PHYEXP_OK';
  if(!checks.toolResult)error='工具结果已发送，但模型未返回约定的确认文本。';
 } catch(e) {error=credentials?credentials.redact(e.message).slice(0,1000):'凭据不可用，请检查宿主登录或保存的 API Key。';}
 finally {
  gateway?.abort();
  let timer;
  try{await Promise.race([runtime?.dispose(),new Promise(resolve=>{timer=setTimeout(resolve,1500)})]);}catch{}finally{clearTimeout(timer)}
  credentials?.dispose();fs.rmSync(dir,{recursive:true,force:true});
 }
 if(!checks.stream&&!error)error='未观察到流式增量响应。';
 return {passed:Object.values(checks).every(Boolean),checks,error:error||null,requests,
  durationMs:Date.now()-started};
}

if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href){
 let input='';for await(const part of process.stdin){input+=part;if(input.length>262144)throw Error('Test request too large')}
 const result=await probeProvider(JSON.parse(input));
 process.stdout.write('PHYEXP_PROVIDER_TEST='+JSON.stringify(result)+'\n',()=>process.exit(0));
}
