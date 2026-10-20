import fs from 'node:fs';
import {build} from 'esbuild';
for (const name of ['meta-workbench','meta-workbench-studio']) {
 const result=await build({entryPoints:[`packages/${name}/client/index.tsx`],bundle:true,write:false,format:'cjs',platform:'browser',external:['react','react/jsx-runtime'],jsx:'automatic'});
 fs.mkdirSync(`packages/${name}/lib`,{recursive:true});
 fs.writeFileSync(`packages/${name}/lib/client.js`,`window.__ModuleLoader__.load({id:'@phyexp/${name}',factory:(require)=>{const module={exports:{}};const exports=module.exports;\n${result.outputFiles[0].text}\nreturn module.exports;}});\n`);
 console.log(`Built native ${name} client`);
}
