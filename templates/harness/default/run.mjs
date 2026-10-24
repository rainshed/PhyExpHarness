import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import {spawn} from 'node:child_process';
const context=JSON.parse(fs.readFileSync(process.env.PHYEXP_CONTEXT));
const root=import.meta.dirname,output=context.outputDirectory;
fs.mkdirSync(output,{recursive:true});
const config=JSON.parse(fs.readFileSync(path.join(root,'harness.json'))).runtimeConfig;
const channel=context.modelChannel;
const api=channel.codexSubscription?'openai-codex-responses':channel.protocol==='responses'?'openai-responses':channel.protocol==='anthropic'?'anthropic-messages':'openai-completions';
const effort=context.solver.reasoningEffort;
const model={id:context.solver.model,contextWindow:config.contextWindow,maxTokens:config.maxTokens,
 reasoningEfforts:effort===undefined?false:{off:null,low:'low',medium:'medium',high:'high',xhigh:'xhigh',max:'max'}};
const insert=[{id:'candidate-provider',name:'@deepseek-ai/dsh-llm-pi-ai',config:{providers:{solver:{api,
 baseURL:channel.url+(channel.codexSubscription?'/codex':channel.protocol==='completions'?'/v1':''),
 apiKeyEnv:'CANDIDATE_MODEL_TOKEN',transport:'sse',models:[model],retryPolicy:{mode:'normal',maxRetries:0}}}}},
 ...context.mcpServers.map((server,i)=>({id:'task-mcp-'+i,name:'@deepseek-ai/dsh-mcp-client',
 config:{serverName:server.name,transport:server.transport,url:server.url,failOnStartupError:true,
 toolCallTimeoutMs:Math.max(1,context.deadline*1000-Date.now()),reconnect:{enabled:true}}}))];
if(config.recovery)insert.push({id:'candidate-recovery',name:path.join(root,'recovery/plugin.mjs'),config:{policy:config.recovery,deadline:context.deadline*1000}});
for(const plugin of config.plugins||[])insert.push({...plugin,name:plugin.name.startsWith('.')?path.resolve(root,plugin.name):plugin.name});
const patch=[{id:'llm-deepseek',disabled:true},{id:'tool-fs',config:{read:true,readImage:true,write:true,edit:true}},
 {id:'persistent-bash',config:{timeoutMs:Math.max(1,context.deadline*1000-Date.now())}},
 {id:'terminal-bash',config:{timeoutMs:Math.max(1,context.deadline*1000-Date.now())}},
 {insert},...(config.patches||[])];
const patchFile=path.join(output,'patches.json');fs.writeFileSync(patchFile,JSON.stringify(patch));
const child=spawn(process.execPath,[path.join(root,'boot.mjs'),patchFile],{cwd:context.workspace,
 env:{...process.env,DSH_HOME:path.join(output,'dsh'),CANDIDATE_MODEL_TOKEN:channel.token},stdio:['pipe','pipe','pipe']});
child.stderr.pipe(process.stderr);const lines=readline.createInterface({input:child.stdout});
let sequence=0,turn;const pending=new Map(),events=[];
const ended=new Promise(resolve=>child.once('exit',(code,signal)=>{for(const waiter of pending.values())waiter.reject(new Error('Harness exited'));turn?.reject(new Error('Harness exited'));resolve({code,signal});}));
lines.on('line',line=>{
 let message;try{message=JSON.parse(line);}catch{process.stderr.write(line+'\n');return;}
 if(message.id!==undefined&&!message.method){const waiter=pending.get(String(message.id));if(waiter){pending.delete(String(message.id));message.error?waiter.reject(new Error(JSON.stringify(message.error))):waiter.resolve(message.result);}}
 if(message.method==='session.event'){
  events.push(message.params.event);fs.writeFileSync(path.join(output,'events.json'),JSON.stringify(events));
  if(turn&&message.params.sessionId===turn.id&&message.params.event.type==='agent/inbox/spliced')turn.received=true;
 }
 if(turn&&turn.received&&message.method==='session.status'&&message.params.sessionId===turn.id&&message.params.status==='idle')turn.resolve();
});
function request(method,params){const id=String(++sequence);return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});}
try{
 await request('initialize',{cwd:context.workspace,provider:'solver',model:context.solver.model,...(effort===undefined?{}:{reasoningEffort:effort}),maxTokens:config.maxTokens});
 const sessions=config.sessions||1;
 for(let i=0;i<sessions;i++){
  const id='solver-'+i;const idle=new Promise((resolve,reject)=>turn={id,resolve,reject,received:false});idle.catch(()=>{});
  const prompt=context.instruction+'\n\nTask environment:\n'+JSON.stringify({workspace:context.workspace,mcpServers:context.mcpServers,deadline:new Date(context.deadline*1000).toISOString()})+(config.promptSuffix||'');
  await request('session/prompt',{sessionId:id,contentBlocks:[{type:'text',text:prompt}]});await idle;turn=null;
  if(events.filter(e=>e.type==='turn/end').at(-1)?.data.reason.kind==='error')process.exitCode=1;
 }
 await request('shutdown',null);const result=await ended;
 if(result.code)process.exitCode=result.code;
}catch(error){process.stderr.write(String(error.stack||error)+'\n');child.kill('SIGTERM');process.exitCode=1;}
finally{fs.writeFileSync(path.join(output,'events.json'),JSON.stringify(events));lines.close();}
