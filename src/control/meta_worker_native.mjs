// Credentials and cross-role authority live only in this outside supervisor.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createProviderCredentials} from '../execution/host/provider_auth.mjs';
import {providerRuntime} from '../execution/host/model_gateway.mjs';
import {budgetGate} from '../execution/host/budget.mjs';
import {modelAccess} from '../execution/host/model_access.mjs';
import {MetaGateway} from './meta_gateway.mjs';
import {MetaHost} from './meta_host.mjs';
const config=JSON.parse(fs.readFileSync(process.argv[2]));
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const logs=path.dirname(process.argv[2]);const base=process.env.PHYEXP_CONTROL_URL;const token=process.env.PHYEXP_META_TOKEN;
const nativeId=config.nativeSessionId||config.id;
let credentials,provider,gateway,host,session,timer,watchdog,closing=false,cursor=config.cursor||0;
const summary={status:'starting',runtimeVersion:'meta-runtime-v2',nativeSessionId:nativeId,startedAt:new Date().toISOString(),turns:0};
async function api(route,body){
 const response=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{authorization:'Bearer '+token,'content-type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(45000)});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'Control interface unavailable');return result;
}
const unmetered=config.modelAccessPolicy==='control-only-v1';
const budget=unmetered?modelAccess({deadline:config.deadline*1000,url:base+'/model-access/'+config.leaseId,token}):budgetGate({deadline:config.deadline*1000,softTokenLimit:config.softTokenLimit,url:base+'/accounting/'+config.leaseId,token,purpose:'meta'});
function save(){
 if(gateway)Object.assign(summary,gateway.diagnostics(summary));summary.cursor=cursor;if(budget.snapshot)summary.accounting=budget.snapshot();
 const redact=value=>credentials?credentials.redact(value):value;
 // Child events live in their native sessions; keep the main archive unambiguous.
 const events=session?.messages.filter(m=>m.method==='session.event'&&m.params.sessionId===nativeId).map(m=>m.params.event)||[];
 fs.writeFileSync(path.join(logs,'events.json'),redact(JSON.stringify(events))+'\n');
 const file=path.join(logs,'summary.json');fs.writeFileSync(file+'.tmp',redact(JSON.stringify(summary,null,2))+'\n');fs.renameSync(file+'.tmp',file);
}
async function stop(){if(closing)return;closing=true;summary.status='interrupted';save();await host?.dispose();credentials?.dispose();process.exit(143);}
try{
 credentials=createProviderCredentials(config.model,{providerConfig:config.providerConfig,minimumValidityMs:Math.max(120000,config.deadline*1000-Date.now()+120000)});
 provider=await providerRuntime({model:config.model,credentialFile:credentials.credentialFile,providerConfig:config.providerConfig});
 gateway=new MetaGateway({mainSessionId:nativeId,model:config.model,adapter:provider,deadline:config.deadline*1000,audit:path.join(logs,'gateway-audit.jsonl'),
  reserve:async(id,request,options)=>{await budget.reserve(id,request,options);if(!unmetered)await api('/meta-sessions/'+config.id+'/runtime',{action:'model_request',input:{id,agentId:request.sessionId}});},settle:budget.settle,redact:credentials.redact});
 const frozen=JSON.parse(fs.readFileSync(path.join(config.metaCompositionRoot,'manifest.json')));
 host=new MetaHost({config,frozen,root,logs,api,gateway,modelInfo:provider.info,image:frozen.runnerImage});session=host.create(nativeId,'meta');
 process.once('SIGTERM',stop);process.once('SIGINT',stop);watchdog=setTimeout(stop,Math.max(1,config.deadline*1000-Date.now()));timer=setInterval(save,3000);
 await session.request('initialize',{...config.model,cwd:'/work'});
 if(config.resumeSession){
  try{await session.request('session/resume',{sessionId:nativeId});summary.resumed=true;}
  catch(error){summary.resumeFailed=true;throw error;}
 }
 let prompt=config.prompt,pendingCursor=null;
 while(Date.now()<config.deadline*1000){
  if(prompt){
   summary.status='running';save();
   await session.prompt(nativeId,prompt,Math.max(1,config.deadline*1000-Date.now()));
   // Let the native manager deliver child messages and settle owned research
   // before the controller issues another idle nudge. No separate child timer.
   await session.request('session/wait',{sessionId:nativeId},Math.max(1,config.deadline*1000-Date.now()));
   summary.turnEnd=session.messages.filter(m=>m.method==='session.event'&&m.params.sessionId===nativeId&&m.params.event.type==='turn/end').at(-1)?.params.event.data.reason;
   if(summary.turnEnd?.kind!=='completed')throw new Error('Meta turn did not complete');
   summary.turns++;summary.status='waiting';save();prompt=null;
   if(pendingCursor!==null){await api('/meta-sessions/'+config.id+'/ack',{cursor:pendingCursor});cursor=pendingCursor;pendingCursor=null;}
  }
  const notice=await api('/meta-sessions/'+config.id+'/notifications?after='+cursor);
  if(notice.finish){summary.status='completed';break;}
  if((notice.events.total??notice.events.length)||notice.continue){
   pendingCursor=notice.cursor;
   prompt=JSON.stringify({source:'Fixed controller notification',delivery:{consumer:nativeId,after:cursor,through:notice.cursor},events:notice.events,status:notice.status,evidenceIndex:'/evidence/index.json',instruction:'Continue research or finish outstanding reports within the activity limits. A completed conversation turn does not end the activity. Reconcile any operation with an unknown outcome before submitting another.'});
  }else if(notice.cursor>cursor){await api('/meta-sessions/'+config.id+'/ack',{cursor:notice.cursor});cursor=notice.cursor;}
  await new Promise(resolve=>setTimeout(resolve,1000));
 }
 await session.shutdown();
}catch(error){summary.status='error';summary.error=credentials?credentials.redact(String(error.stack||error)):String(error);summary.failure=gateway?.firstFailure;process.exitCode=1;}
finally{
 clearInterval(timer);clearTimeout(watchdog);summary.finishedAt=new Date().toISOString();save();
 await host?.dispose();await provider?.dispose();credentials?.dispose();save();
}
process.exit(process.exitCode||0);
