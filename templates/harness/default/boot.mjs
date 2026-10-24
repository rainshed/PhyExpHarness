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
