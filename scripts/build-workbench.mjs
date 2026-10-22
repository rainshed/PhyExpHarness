import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {readWorkbenchUIs,selectWorkbenchUIs} from './workbench-uis.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const registry=readWorkbenchUIs(root);
for(const ui of selectWorkbenchUIs(registry,process.env.PHYEXP_UI_VARIANT||'all')){
 const result=await build({entryPoints:[ui.client],bundle:true,write:false,format:'cjs',platform:'browser',external:['react','react/jsx-runtime'],jsx:'automatic'});
 fs.mkdirSync(path.join(ui.directory,'lib'),{recursive:true});
 fs.writeFileSync(path.join(ui.directory,'lib/client.js'),`window.__ModuleLoader__.load({id:${JSON.stringify(ui.package)},factory:(require)=>{const module={exports:{}};const exports=module.exports;\n${result.outputFiles[0].text}\nreturn module.exports;}});\n`);
 console.log(`Built native ${ui.id} client`);
}
