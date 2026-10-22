import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {build} from 'esbuild';
import {Context,Service} from '@deepseek-ai/cordis';
import * as bridge from '../../packages/meta-workbench-bridge/index.mjs';
import * as studioHost from '../../packages/meta-workbench-studio/host/index.mjs';

// Exercise the production client entry points with native Cordis effect ownership.
// The browser contract separately exercises the real renderer and host layout.
class Slots extends Service {
 constructor(ctx){super(ctx,'slots');this.items=new Map();}
 inject(name,callback){return this.ctx.effect(callback);}
 register(spec,component){return this.ctx.effect(()=>{
  const key=spec.name+'/'+(spec.key||spec.id);
  assert.ok(!this.items.has(key),'duplicate contribution '+key);
  this.items.set(key,{spec,component});return()=>{this.items.delete(key)};
 });}
}
async function client(name){
 const result=await build({entryPoints:[`packages/${name}/client/index.tsx`],bundle:true,write:false,format:'cjs',
  platform:'browser',external:['react','react/jsx-runtime'],jsx:'automatic'});
 const sandbox={module:{exports:{}},exports:null,require:id=>{
  assert.ok(['react','react/jsx-runtime'].includes(id),'only shared React is external');
  return {createElement(){},Fragment:Symbol('Fragment'),jsx(){},jsxs(){}};
 }};
 sandbox.exports=sandbox.module.exports;
 vm.runInNewContext(result.outputFiles[0].text,sandbox);
 return sandbox.module.exports;
}

test('Studio and an independent UI unload while one authenticated bridge remains',async()=>{
 const previous={url:process.env.PHYEXP_CONTROL_URL,token:process.env.PHYEXP_USER_TOKEN};
 process.env.PHYEXP_CONTROL_URL='http://127.0.0.1:1';process.env.PHYEXP_USER_TOKEN='fixture-only';
 const ctx=new Context();let routes=0;
 ctx.provide('webServer',{register:route=>{assert.equal(route.path,'/phyexp/api');routes++;return()=>routes--}});
 ctx.provide('connection',{requestRejection:()=>undefined});
 ctx.provide('layout',{selectPanel(){}});
 try{
  await ctx.plugin(Slots).await();
  const route=ctx.plugin(bridge);await route.await();
  const studio=await client('meta-workbench-studio');
  const alternative={inject:['slots'],apply(ctx){ctx.slots.inject('main',()=>ctx.slots.register({name:'main',key:'temporary-ui'},()=>null))}};
  const sh=ctx.plugin(studioHost);await sh.await();
  assert.equal(routes,1,'UI hosts must not register API routes');
  const first=ctx.plugin(alternative),second=ctx.plugin(studio);await first.await();await second.await();
  assert.equal(ctx.slots.items.size,3);
  assert.ok(ctx.slots.items.has('main/phyexp-workbench-studio'));
  assert.ok(ctx.slots.items.has('main/temporary-ui'));
  await first.dispose();
  assert.equal(ctx.slots.items.size,2);assert.equal(routes,1);
  await second.dispose();await sh.dispose();
  assert.equal(ctx.slots.items.size,0);assert.equal(routes,1);
  const reloaded=ctx.plugin(studio);await reloaded.await();assert.equal(ctx.slots.items.size,2);
  await reloaded.dispose();assert.equal(ctx.slots.items.size,0);
  await route.dispose();assert.equal(routes,0);
 }finally{
  await ctx.fiber.dispose();
  for(const [name,value] of [['PHYEXP_CONTROL_URL',previous.url],['PHYEXP_USER_TOKEN',previous.token]]){
   if(value===undefined)delete process.env[name];else process.env[name]=value;
  }
 }
});
