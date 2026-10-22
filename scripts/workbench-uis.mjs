import fs from 'node:fs';
import path from 'node:path';

export function readWorkbenchUIs(root){
 const manifest=JSON.parse(fs.readFileSync(path.join(root,'profiles/meta-workbench/uis.json'),'utf8'));
 if(manifest.version!==1||!Array.isArray(manifest.uis)||!manifest.uis.length)throw Error('Invalid workbench UI registry');
 const packages=new Map();
 for(const item of fs.readdirSync(path.join(root,'packages'),{withFileTypes:true})){
  if(!item.isDirectory())continue;
  const directory=path.join(root,'packages',item.name),file=path.join(directory,'package.json');
  if(fs.existsSync(file)){const pkg=JSON.parse(fs.readFileSync(file,'utf8'));packages.set(pkg.name,{directory,pkg});}
 }
 const ids=new Set(),names=new Set();
 const uis=manifest.uis.map(entry=>{
  if(!/^[a-z][a-z0-9-]*$/.test(entry.id)||['all','both'].includes(entry.id)||ids.has(entry.id)||names.has(entry.package))throw Error('Invalid or duplicate workbench UI: '+entry.id);
  ids.add(entry.id);names.add(entry.package);
  const item=packages.get(entry.package);
  if(!item||item.pkg.phyexpWorkbench?.kind!=='ui')throw Error('Missing UI package declaration: '+entry.package);
  const {directory,pkg}=item,host=path.join(directory,'host/index.mjs'),client=path.join(directory,'client/index.tsx');
  if(!fs.existsSync(host)||!fs.existsSync(client)||pkg.exports?.['./client']!=='./lib/client.js'||pkg.exports?.['.']!=='./host/index.mjs')throw Error('Invalid UI entry points: '+entry.package);
  return {...entry,directory,host,client,pluginId:entry.package.replace(/^@/,'').replace('/','-')};
 });
 if(!ids.has(manifest.default))throw Error('Workbench default UI is not registered: '+manifest.default);
 return {default:manifest.default,uis};
}

export function selectWorkbenchUIs(registry,selection=registry.default){
 // "both" remains a compatibility alias for older launcher environments.
 const ids=['all','both'].includes(selection)?registry.uis.map(ui=>ui.id):selection.split(',').map(id=>id.trim());
 if(!ids.length||new Set(ids).size!==ids.length)throw Error('Invalid workbench UI selection');
 return ids.map(id=>{
  const ui=registry.uis.find(entry=>entry.id===id);
  if(!ui)throw Error(`Unknown workbench UI "${id}". Available: ${registry.uis.map(ui=>ui.id).join(', ')}`);
  return ui;
 });
}
