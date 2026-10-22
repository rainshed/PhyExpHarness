import {readWorkbenchUIs,selectWorkbenchUIs} from './workbench-uis.mjs';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {spawn} from 'node:child_process';import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const selectedUIs=selectWorkbenchUIs(readWorkbenchUIs(root),process.env.PHYEXP_UI_VARIANT);
const data=process.env.PHYEXP_DATA_DIR||path.join(os.homedir(),process.platform==='darwin'?'Library/Application Support/PhyExpHarness':'.local/share/PhyExpHarness');
process.env.PHYEXP_CONTROL_URL||='http://127.0.0.1:18402';
if(!process.env.PHYEXP_USER_TOKEN)process.env.PHYEXP_USER_TOKEN=fs.readFileSync(path.join(data,'user-token'),'utf8').trim();
const home=process.env.PHYEXP_UI_HOME||path.join(data,'ui');fs.mkdirSync(home,{recursive:true});
const accessFile=path.join(home,'workbench-access.json');
const access=fs.existsSync(accessFile)?JSON.parse(fs.readFileSync(accessFile,'utf8')):{};
const publicUrl=process.env.PHYEXP_UI_PUBLIC_URL??access.publicUrl;
const webArgs=['--host','127.0.0.1'];
if(publicUrl){
 const url=new URL(publicUrl);
 if(url.protocol!=='https:'||url.username||url.password||url.pathname!=='/'||url.search||url.hash)throw new Error('PHYEXP_UI_PUBLIC_URL must be an HTTPS root URL without credentials, query or fragment');
 webArgs.push('--public-url',url.origin+'/', '--trusted-host',url.host);
}
const plugins=[{id:'phyexp-meta-workbench-bridge',name:path.join(root,'packages/meta-workbench-bridge/index.mjs')},...selectedUIs.map(ui=>({id:ui.pluginId,name:ui.host}))];
const patch=path.join(home,'workbench.patch.json');fs.writeFileSync(patch,JSON.stringify([{insert:plugins}]));
const child=spawn(path.join(root,'node_modules/.bin/dsh'),['web','--patch',patch,'--no-open','--port',process.env.PHYEXP_UI_PORT||'18401',...webArgs],{env:{...process.env,DSH_HOME:home},stdio:'inherit'});
process.on('SIGTERM',()=>child.kill('SIGTERM'));process.on('SIGINT',()=>child.kill('SIGINT'));child.on('exit',code=>process.exit(code??1));
