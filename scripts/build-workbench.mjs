import fs from 'node:fs';
import {build} from 'esbuild';
const result=await build({entryPoints:['packages/meta-workbench/client/index.tsx'],bundle:true,write:false,format:'cjs',platform:'browser',external:['react','react/jsx-runtime'],jsx:'automatic'});
fs.mkdirSync('packages/meta-workbench/lib',{recursive:true});
fs.writeFileSync('packages/meta-workbench/lib/client.js',`window.__ModuleLoader__.load({id:'@phyexp/meta-workbench',factory:(require)=>{const module={exports:{}};const exports=module.exports;\n${result.outputFiles[0].text}\nreturn module.exports;}});\n`);
console.log('Built native workbench client');
