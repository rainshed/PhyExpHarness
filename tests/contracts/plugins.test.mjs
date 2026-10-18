import test from 'node:test';import assert from 'node:assert/strict';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import {Context} from '@deepseek-ai/cordis';import {ToolRuntime} from '@deepseek-ai/dsh-tools';
import * as meta from '../../packages/meta-harness/index.mjs';
import {apply as workbench} from '../../packages/meta-workbench/host/index.mjs';
test('Meta tool registration and disposal use native Cordis scopes',async()=>{
 const ctx=new Context();await ctx.plugin(SystemPrompt).await();await ctx.plugin(ToolRuntime).await();const plugin=ctx.plugin(meta);await plugin.await();
 assert.equal(ctx.tools.schemas().length,Object.keys(meta.operations).length+2);
 assert.ok(ctx.tools.schemas().some(t=>t.name==='sdk_inspect'));
 await plugin.dispose();assert.equal(ctx.tools.schemas().length,0);await ctx.fiber.dispose();
});
test('workbench owns only its route; refuses cross-origin and path traversal',async()=>{
 process.env.PHYEXP_CONTROL_URL='http://127.0.0.1:18402';process.env.PHYEXP_USER_TOKEN='m0-user';let route,removed=false,dispose;
 workbench({effect:fn=>{dispose=fn();},webServer:{register:r=>{route=r;return()=>{removed=true;};}}});
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
 const ctx=new Context();await ctx.plugin(SystemPrompt).await();await ctx.plugin(ToolRuntime).await();await ctx.plugin(meta).await();
 const signal=new AbortController().signal;
 const result=await ctx.tools.execute({callId:'list',name:'cordis_inspect_list',arguments:{},signal});
 assert.equal(result.value.providers.length,1);assert.equal(result.value.providers[0].id,'execution-sdk');
 for(const platform of ['client','host']){
  const denied=await ctx.tools.execute({callId:platform,name:'cordis_inspect_query',arguments:{platform,provider:'credentials',method:'resolve'},agent:{id:'test'},signal});
  assert.equal(denied.isError,true);
 }
 await ctx.fiber.dispose();
});
