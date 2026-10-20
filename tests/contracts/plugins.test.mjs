import test from 'node:test';import assert from 'node:assert/strict';
import fs from 'node:fs';import path from 'node:path';import {fileURLToPath,pathToFileURL} from 'node:url';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import {Context} from '@deepseek-ai/cordis';import {ToolRuntime} from '@deepseek-ai/dsh-tools';
import * as meta from '../../packages/meta-harness/index.mjs';
import {apply as workbench} from '../../packages/meta-workbench-bridge/index.mjs';
test('Markdown tool example returns structured values, rejects invalid calls and unloads',async()=>{
 const guide=fs.readFileSync(new URL('../../knowledge/plugin-sdk/guides/tools.md',import.meta.url),'utf8');
 const source=guide.match(/```js\n([\s\S]*?)\n```/)[1];
 const manifest=JSON.parse(guide.match(/```json\n([\s\S]*?)\n```/)[1]);
 const dir=fs.mkdtempSync(fileURLToPath(new URL('../../node_modules/.guide-example-',import.meta.url)));
 const ctx=new Context();
 try{
  fs.writeFileSync(path.join(dir,manifest.entry),source);
  await ctx.plugin(SystemPrompt).await();await ctx.plugin(ToolRuntime).await();
  const plugin=ctx.plugin(await import(pathToFileURL(path.join(dir,manifest.entry)).href));await plugin.await();
  assert.deepEqual(ctx.tools.schemas().map(t=>t.name),manifest.tools);
  const execute=(args,signal=new AbortController().signal)=>ctx.tools.execute({callId:'guide',name:'summarize_numbers',arguments:args,signal});
  for(const [values,expected] of [[[1,2,3],{count:3,sum:6}],[[],{count:0,sum:0}]]){
   const result=await execute({values});assert.equal(result.isError,false);assert.deepEqual(result.value,expected);
   assert.deepEqual(JSON.parse(result.content[0].text),expected);
  }
  for(const args of [{},{values:['bad']},{values:[Number.MAX_VALUE,Number.MAX_VALUE]}])assert.equal((await execute(args)).isError,true);
  assert.equal((await execute({values:[1]},AbortSignal.abort())).isError,true);
  await plugin.dispose();assert.equal(ctx.tools.schemas().length,0);
 }finally{await ctx.fiber.dispose();fs.rmSync(dir,{recursive:true,force:true});}
});
test('Meta tool registration and disposal use native Cordis scopes',async()=>{
 const ctx=new Context();await ctx.plugin(SystemPrompt).await();await ctx.plugin(ToolRuntime).await();const plugin=ctx.plugin(meta,{systemPrompt:'Fixed controller fixture: exercise tool registration and permissions.'});await plugin.await();
 assert.equal(ctx.tools.schemas().length,Object.keys(meta.operations).length+2);
 assert.ok(ctx.tools.schemas().some(t=>t.name==='sdk_inspect'));
 await plugin.dispose();assert.equal(ctx.tools.schemas().length,0);await ctx.fiber.dispose();
});
test('workbench owns only its route; refuses cross-origin and path traversal',async()=>{
 process.env.PHYEXP_CONTROL_URL='http://127.0.0.1:18402';process.env.PHYEXP_USER_TOKEN='m0-user';let route,removed=false,dispose;
 workbench({connection:{requestRejection:()=>undefined},effect:fn=>{dispose=fn();},webServer:{register:r=>{route=r;return()=>{removed=true;};}}});
 const response=()=>({status:0,text:'',writeHead(code){this.status=code;return this;},end(text){this.text=text;return this;}});
 for(const req of [{method:'POST',url:'/phyexp/api/campaigns',headers:{origin:'https://outside.example',host:'127.0.0.1:18401'}},
 {method:'POST',url:'/phyexp/api/campaigns',headers:{host:'127.0.0.1:18401'}},
 {method:'GET',url:'/phyexp/api/%2e%2e/secrets',headers:{host:'127.0.0.1:18401'}}]){
 const res=response();await route.handler(req,res);assert.ok([400,403].includes(res.status));}
 dispose();assert.ok(removed);
 delete process.env.PHYEXP_CONTROL_URL;delete process.env.PHYEXP_USER_TOKEN;
});

test('public context and result policy work and disappear on dependency removal',async()=>{
 const ctx=new Context();const base=ctx.plugin(SystemPrompt);await base.await();const runtime=ctx.plugin(ToolRuntime);await runtime.await();
 const example=await import('../../knowledge/plugin-sdk/examples/echo.mjs');const plugin=ctx.plugin(example,{prefix:'seen:'});await plugin.await();
 const result=await ctx.tools.execute({callId:'a',name:'example_echo',arguments:{text:'hello'},signal:new AbortController().signal});
 assert.equal(result.isError,false);assert.equal(result.value,'seen:hello');
 assert.ok((await ctx.systemPrompt.assemble()).contexts.some(x=>x.name==='example-context'));
 await plugin.dispose();assert.equal(ctx.tools.schemas().length,0);assert.equal((await ctx.systemPrompt.assemble()).contexts.length,0);
 const dependent=ctx.plugin(example);await dependent.await();assert.equal(ctx.tools.schemas().length,1);
 await runtime.dispose();assert.equal((await ctx.systemPrompt.assemble()).contexts.length,0);await ctx.fiber.dispose();
});

test('native inspect tools expose only execution declarations, with no client or credential registry',async()=>{
 const ctx=new Context();await ctx.plugin(SystemPrompt).await();await ctx.plugin(ToolRuntime).await();await ctx.plugin(meta,{systemPrompt:'Fixed controller fixture: exercise tool registration and permissions.'}).await();
 const signal=new AbortController().signal;
 const result=await ctx.tools.execute({callId:'list',name:'cordis_inspect_list',arguments:{},signal});
 assert.equal(result.value.providers.length,1);assert.equal(result.value.providers[0].id,'execution-sdk');
 for(const platform of ['client','host']){
  const denied=await ctx.tools.execute({callId:platform,name:'cordis_inspect_query',arguments:{platform,provider:'credentials',method:'resolve'},agent:{id:'test'},signal});
  assert.equal(denied.isError,true);
 }
 await ctx.fiber.dispose();
});
