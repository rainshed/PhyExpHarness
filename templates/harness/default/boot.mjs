import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import {boot,installFailLoud} from '@deepseek-ai/dsh-app-boot';
import {provideCmdline} from '@deepseek-ai/dsh-cmdline';
let ctx,ready=false,closing=false;const listeners=new Set();
const exit=async code=>{if(closing)return;closing=true;try{await ctx?.fiber.dispose();}finally{process.exit(code);}};
installFailLoud('candidate-harness',process,()=>ctx?.fiber.dispose());
for(const signal of ['SIGTERM','SIGINT'])process.once(signal,()=>exit(143));
ctx=await boot('candidate-harness',fileURLToPath(new URL('./profile.yml',import.meta.url)),JSON.parse(fs.readFileSync(process.argv[2])),host=>{
 ctx=host;provideCmdline(host,{args:[],exit,ready:{onReady(fn){if(ready)fn();else listeners.add(fn);return()=>listeners.delete(fn);}}});
},import.meta.url);
ready=true;for(const fn of listeners)fn();listeners.clear();

if(process.env.PHYEXP_ASSEMBLY_CHECK==='1'){
 const wanted=JSON.parse(process.env.PHYEXP_CHECK_PLUGIN_IDS||'[]');
 const entries=[...ctx.loader.entries()];
 const receipt=wanted.map(id=>{const entry=entries.find(e=>e.options.id===id);return {id,state:entry?.fiber?.state??null};});
 fs.writeFileSync(process.env.PHYEXP_CHECK_RECEIPT,JSON.stringify({kind:'native-plugin-load',plugins:receipt}));
 if(receipt.some(entry=>entry.state!==2)){process.stderr.write('Selected plugins did not activate: '+JSON.stringify(receipt)+'\n');await exit(1);}
 await exit(0);
}
