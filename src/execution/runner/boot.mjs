// Headless deployment of the upstream sdk-minimal entry tree. No CLI/UI profile installation.
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import {boot, installFailLoud} from '@deepseek-ai/dsh-app-boot';
import {requestHost} from './gateway_plugin.mjs';
import {provideCmdline} from '@deepseek-ai/dsh-cmdline';
let ctx; let closing = false; let ready = false; const listeners=new Set();
const exit = async code => {
 if(closing)return; closing=true; const timer=setTimeout(()=>process.exit(code),2000);
 try {await ctx?.fiber.dispose();} finally {clearTimeout(timer);process.exit(code);}
};
installFailLoud('phyexp-sdk',process,()=>ctx?.fiber.dispose());
process.once('SIGTERM',()=>exit(143));process.once('SIGINT',()=>exit(130));
ctx=await boot('phyexp-sdk',fileURLToPath(new URL('./assets/sdk-minimal.yml',import.meta.url)),
 JSON.parse(fs.readFileSync(process.argv[2])),host=>{
  ctx=host;provideCmdline(host,{args:[],exit,ready:{onReady(fn){if(ready)fn();else listeners.add(fn);return()=>listeners.delete(fn);}}});
 },import.meta.url);
const entries=[...ctx.loader.entries()].map(e=>({id:e.options.id,name:e.options.name,state:e.fiber?.state,disabled:e.options.disabled===true}));
const patches=JSON.parse(fs.readFileSync(process.argv[2]));
for(const plugin of patches.flatMap(p=>p.insert||[])){
 if(!entries.some(e=>e.id===plugin.id&&e.state===2))throw new Error('Required plugin failed to load: '+plugin.id);
}
const schemas=ctx.tools.schemas();
for await(const _ of requestHost('receipt',{kind:'bootstrap',entries,tools:schemas.map(t=>t.name).sort(),schemas})){}
ready=true;for(const fn of listeners)fn();listeners.clear();
