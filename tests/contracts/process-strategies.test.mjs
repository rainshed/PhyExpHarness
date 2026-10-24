import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';

async function run(configure,reply){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-strategy-')),project=path.join(root,'candidate');
 fs.cpSync('templates/harness/default',project,{recursive:true});fs.symlinkSync(path.resolve('node_modules'),path.join(project,'node_modules'),'dir');
 const spec=JSON.parse(fs.readFileSync(path.join(project,'harness.json')));configure(spec,project);fs.writeFileSync(path.join(project,'harness.json'),JSON.stringify(spec));
 const calls=[];let providerError;
 const server=http.createServer(async(req,res)=>{
  try{
   let input='';for await(const bytes of req)input+=bytes;const body=JSON.parse(input);calls.push(body);
   const output=reply(body,calls.length,root);
   res.writeHead(200,{'content-type':'text/event-stream'});
   if(output.disconnect){res.destroy();return;}
   const delta=output.calls?{role:'assistant',tool_calls:output.calls.map((c,i)=>({index:i,id:'c'+calls.length+'-'+i,type:'function',function:{name:c.name,arguments:typeof c.args==='string'?c.args:JSON.stringify(c.args)}}))}:{role:'assistant',content:output.text||'done'};
   for(const chunk of [{choices:[{index:0,delta,finish_reason:null}]},{choices:[{index:0,delta:{},finish_reason:output.calls?'tool_calls':'stop'}]}])res.write('data: '+JSON.stringify({id:'r'+calls.length,object:'chat.completion.chunk',model:'fixture',...chunk})+'\n\n');
   res.end('data: [DONE]\n\n');
  }catch(error){providerError=error;res.writeHead(500);res.end('fixture assertion failed');}
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const context={instruction:'Exercise candidate strategy.',workspace:root,outputDirectory:path.join(root,'out'),solver:{model:'fixture'},mcpServers:[],deadline:Date.now()/1000+70.12345,
  modelChannel:{protocol:'completions',url:'http://127.0.0.1:'+server.address().port,token:'fixture'}};
 const file=path.join(root,'context.json');fs.writeFileSync(file,JSON.stringify(context));
 const child=spawn(process.execPath,[path.join(project,'run.mjs')],{env:{...process.env,PHYEXP_CONTEXT:file},stdio:['ignore','pipe','pipe']});
 let stderr='';child.stderr.on('data',b=>stderr+=b);child.stdout.resume();const timer=setTimeout(()=>child.kill('SIGKILL'),65000);
 try{
  const [code]=await once(child,'exit');if(providerError)throw providerError;
  return {code,stderr,calls,events:JSON.parse(fs.readFileSync(path.join(root,'out/events.json'))),sideEffects:fs.existsSync(path.join(root,'effects'))?fs.readFileSync(path.join(root,'effects'),'utf8'):''};
 }finally{clearTimeout(timer);server.closeAllConnections();server.close();fs.rmSync(root,{recursive:true,force:true});}
}

test('default recovery does not replay completed side effects and native guards reject invalid complete calls',async()=>{
 const result=await run(()=>{},(body,n)=>{
  if(n===1)return {calls:[{name:'bash',args:{command:"printf first >> effects"}}]};
  if(n===2)return {calls:[{name:'bash',args:'{bad'}]};
  if(n===3)return {calls:[{name:'bash',args:{command:17}},{name:'bash',args:{command:'cat effects'}}]};
  const tools=body.messages.filter(m=>m.role==='tool');assert.ok(tools.some(m=>JSON.stringify(m).includes('first')));
  return {text:'complete'};
 });
 assert.equal(result.code,0,result.stderr);assert.equal(result.sideEffects,'first');assert.ok(result.calls.length>=4);
 const results=result.events.filter(e=>e.type==='tool/result');assert.ok(results.some(e=>JSON.stringify(e).includes('isError')));
});

test('removing recovery is a candidate choice with observable behavior',async()=>{
 const result=await run(spec=>{spec.runtimeConfig.recovery=null;},(_body,n)=>n===1?{calls:[{name:'bash',args:'{bad'}]}:{text:'done'});
 assert.equal(result.calls.length,2);assert.equal(result.code,0,result.stderr);
 assert.ok(!result.events.some(e=>e.type.startsWith('plugin:phyexp-request-recovery/')));
 assert.ok(result.calls[1].messages.some(m=>m.role==='tool'&&JSON.stringify(m).includes('Error')));
});

test('candidate changes sessions, prompt context and profile without platform modification',async()=>{
 const result=await run((spec,project)=>{
  spec.runtimeConfig.sessions=2;spec.runtimeConfig.promptSuffix='\nCANDIDATE_CONTEXT_VARIANT';spec.runtimeConfig.recovery=null;
  spec.runtimeConfig.patches=[{id:'persistent-bash',disabled:true},{id:'terminal-bash',disabled:true}];
  fs.appendFileSync(path.join(project,'profile.yml'),'\n# Candidate-owned profile variation\n');
 },body=>{
  assert.ok(JSON.stringify(body.messages).includes('CANDIDATE_CONTEXT_VARIANT'));
  assert.ok(!body.tools.some(t=>t.function.name==='bash'));return {text:'complete'};
 });
 assert.equal(result.code,0,result.stderr);assert.equal(result.calls.length,2);
});

test('candidate dependency services resolve out of list order and a replacement shell keeps state',async()=>{
 const result=await run((spec,project)=>{
  spec.runtimeConfig.recovery=null;
  spec.runtimeConfig.patches=[{id:'persistent-bash',disabled:true},{id:'terminal-bash',disabled:true}];
  spec.runtimeConfig.plugins=[{id:'consumer',name:'./consumer.mjs'},{id:'provider',name:'./provider.mjs'}];
  fs.writeFileSync(path.join(project,'provider.mjs'),`import {spawn} from 'node:child_process';
export const name='persistent-shell-service';
export function apply(ctx){
 const shell=spawn('/bin/sh',[],{stdio:['pipe','pipe','pipe']});let waiting,output='';
 shell.stdout.on('data',b=>{output+=b;if(output.includes('__END__')){waiting(output.replace('__END__',''));output='';waiting=null;}});
 ctx.provide('candidateShell',{run(command){return new Promise(resolve=>{waiting=resolve;shell.stdin.write(command+'\\nprintf __END__\\n');});}});
 ctx.effect(()=>()=>shell.kill());
}`);
  fs.writeFileSync(path.join(project,'consumer.mjs'),`import {defineTool} from '@deepseek-ai/dsh-tools';
export const name='replacement-terminal';export const inject=['tools','candidateShell'];
export function apply(ctx){ctx.tools.register(defineTool({name:'research_terminal',description:'Persistent task shell',parameters:{command:{type:'string',required:true}},output:{schema:{type:'string'},render:(_,v)=>[{type:'text',text:v}]},execute:({command})=>ctx.candidateShell.run(command)}));}
`);
 },(body,n)=>{
  assert.ok(!body.tools.some(t=>t.function.name==='bash'));
  assert.ok(body.tools.some(t=>t.function.name==='research_terminal'));
  if(n===1)return {calls:[{name:'research_terminal',args:{command:'export FIXTURE_STATE=retained; printf native > effects'}}]};
  if(n===2)return {calls:[{name:'research_terminal',args:{command:'printf "$FIXTURE_STATE"; cat effects'}}]};
  assert.ok(body.messages.some(m=>m.role==='tool'&&JSON.stringify(m).includes('retainednative')));
  return {text:'done'};
 });
 assert.equal(result.code,0,result.stderr);assert.equal(result.sideEffects,'native');assert.equal(result.calls.length,3);
});

for(const cycle of [false,true])test('native dependency diagnostics identify '+(cycle?'a service cycle':'a missing service'),async()=>{
 const result=await run((spec,project)=>{
  spec.runtimeConfig.recovery=null;
  spec.runtimeConfig.plugins=[{id:'fixture-a',name:'./a.mjs'},...(cycle?[{id:'fixture-b',name:'./b.mjs'}]:[])];
  fs.writeFileSync(path.join(project,'a.mjs'),"export const name='fixture-a';export const inject=['fixtureB'];export function apply(ctx){ctx.provide('fixtureA',{});}");
  if(cycle)fs.writeFileSync(path.join(project,'b.mjs'),"export const name='fixture-b';export const inject=['fixtureA'];export function apply(ctx){ctx.provide('fixtureB',{});}");
 },()=>({text:'done'}));
 // The chosen framework can continue with an optional blocked plugin. Its
 // diagnostics must expose the actual dependency; the platform adds no gate.
 assert.match(result.stderr,/fixtureB/);if(cycle)assert.match(result.stderr,/fixtureA/);
});
