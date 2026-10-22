import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {readWorkbenchUIs,selectWorkbenchUIs} from '../../scripts/workbench-uis.mjs';
const repo=fileURLToPath(new URL('../../',import.meta.url));

test('UI registry builds Studio without classic and adds/removes an alternative without editing Studio',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-ui-build-'));
 const write=(name,value)=>{const target=path.join(root,name);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,value)};
 const registry={version:1,default:'studio',uis:[{id:'studio',package:'@phyexp/meta-workbench-studio'}]};
 const save=()=>write('profiles/meta-workbench/uis.json',JSON.stringify(registry));
 const build=(selection)=>execFileSync(process.execPath,['scripts/build-workbench.mjs'],{cwd:root,env:{...process.env,PHYEXP_UI_VARIANT:selection},stdio:'pipe'});
 try{
  for(const name of ['meta-workbench-studio','meta-workbench-client'])fs.cpSync(path.join(repo,'packages',name),path.join(root,'packages',name),{recursive:true,filter:src=>!src.includes('/lib')});
  for(const name of ['build-workbench.mjs','workbench-uis.mjs'])write('scripts/'+name,fs.readFileSync(path.join(repo,'scripts',name)));
  write('schemas/meta-defaults.json',fs.readFileSync(path.join(repo,'schemas/meta-defaults.json')));
  fs.mkdirSync(path.join(root,'node_modules/@phyexp'),{recursive:true});
  fs.symlinkSync(path.join(repo,'node_modules/esbuild'),path.join(root,'node_modules/esbuild'));
  fs.symlinkSync('../../packages/meta-workbench-client',path.join(root,'node_modules/@phyexp/meta-workbench-client'));
  save();assert.equal(fs.existsSync(path.join(root,'packages/meta-workbench')),false);
  build('studio');const original=fs.readFileSync(path.join(root,'packages/meta-workbench-studio/lib/client.js'),'utf8');
  write('packages/alternative/package.json',JSON.stringify({name:'@phyexp/alternative',type:'module',phyexpWorkbench:{kind:'ui'},exports:{'.':'./host/index.mjs','./client':'./lib/client.js'}}));
  write('packages/alternative/host/index.mjs','export function apply(){}');
  write('packages/alternative/client/index.tsx',"import {API} from '@phyexp/meta-workbench-client'; export const endpoint=API;");
  registry.uis.push({id:'alternative',package:'@phyexp/alternative'});save();
  const catalog=readWorkbenchUIs(root);
  assert.deepEqual(selectWorkbenchUIs(catalog).map(ui=>ui.id),['studio']);
  assert.deepEqual(selectWorkbenchUIs(catalog,'alternative,studio').map(ui=>ui.id),['alternative','studio']);
  for(const selector of ['all','both'])assert.equal(selectWorkbenchUIs(catalog,selector).length,2);
  assert.throws(()=>selectWorkbenchUIs(catalog,'classic'),/Unknown/);
  assert.throws(()=>selectWorkbenchUIs(catalog,'studio,studio'),/Invalid/);
  build('alternative');assert.ok(fs.existsSync(path.join(root,'packages/alternative/lib/client.js')));
  build('all');assert.equal(fs.readFileSync(path.join(root,'packages/meta-workbench-studio/lib/client.js'),'utf8'),original);
  fs.rmSync(path.join(root,'packages/alternative'),{recursive:true});registry.uis.pop();save();build('all');
  registry.default='removed';save();assert.throws(()=>readWorkbenchUIs(root),/default UI/);
  registry.default='studio';registry.uis.push({...registry.uis[0]});save();assert.throws(()=>readWorkbenchUIs(root),/duplicate/);
 }finally{fs.rmSync(root,{recursive:true,force:true})}
});
