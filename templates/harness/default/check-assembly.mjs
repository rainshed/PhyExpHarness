// No Solver request: initialize the native plugin tree and verify selected entries.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const root=import.meta.dirname,temporary=fs.mkdtempSync(path.join(os.tmpdir(),'harness-check-'));
try{
 const context={instruction:'',workspace:temporary,outputDirectory:path.join(temporary,'output'),solver:{model:'assembly-check'},mcpServers:[],deadline:Date.now()/1000+60,
  modelChannel:{protocol:'completions',url:'http://127.0.0.1:1',token:'assembly-check'}};
 const file=path.join(temporary,'context.json');fs.writeFileSync(file,JSON.stringify(context));
 execFileSync(process.execPath,[path.join(root,'run.mjs')],{env:{...process.env,PHYEXP_CONTEXT:file,PHYEXP_ASSEMBLY_CHECK:'1'},stdio:'inherit',timeout:60000});
 fs.copyFileSync(path.join(context.outputDirectory,'load-receipt.json'),path.join(root,'assembly-check.json'));
}finally{fs.rmSync(temporary,{recursive:true,force:true});}
