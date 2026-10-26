import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {MetaHost} from '../../src/control/meta_host.mjs';

test('actual Meta mount set exposes selected activity files without the global library',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-library-boundary-'));
 try{
  const filesRoot=path.join(root,'activity/files'),workRoot=path.join(root,'activity/work'),pluginWorkspace=path.join(root,'activity/plugins');
  for(const n of ['evidence','materials','sdk','versions','outputs'])fs.mkdirSync(path.join(filesRoot,n),{recursive:true});
  fs.mkdirSync(pluginWorkspace,{recursive:true});fs.writeFileSync(path.join(pluginWorkspace,'selected.mjs'),'USER_SELECTED_SOURCE');
  fs.mkdirSync(path.join(root,'catalog'));fs.writeFileSync(path.join(root,'catalog/unselected.mjs'),'UNSELECTED_PRIVATE_SOURCE');
  fs.mkdirSync(path.join(root,'objects'));fs.writeFileSync(path.join(root,'objects/unselected.mjs'),'UNSELECTED_PRIVATE_SOURCE');
  fs.writeFileSync(path.join(root,'control.sqlite'),'PRIVATE_CONTROL_DATABASE');
  const privatePaths=['catalog','objects','control.sqlite'].map(n=>path.join(root,n));
  fs.writeFileSync(path.join(filesRoot,'versions/selected.txt'),'USER_SELECTED_SOURCE');
  const frozen={id:'fixture',composition:JSON.parse(fs.readFileSync('packages/meta-harness/composition-native.json')),systemPrompt:{text:'fixture'},reviewerPrompt:'fixture'};
  const base=JSON.parse(fs.readFileSync('templates/harness/default/harness.json')).build.image;
  const captured=[];
  const host=new MetaHost({root:path.resolve('.'),logs:path.join(root,'logs'),frozen,config:{id:'fixture',model:{},workRoot,pluginWorkspace,sessionRoot:path.join(root,'activity/session'),filesRoot},sessionFactory:options=>{captured.push(options);return {}}});
  host.create('main','meta');host.create('review','reviewer');
  for(const [i,options] of captured.entries()){
   for(const mount of options.mounts){
    const source=path.resolve(mount.split(',').find(p=>p.startsWith('source=')).slice(7));
    assert.ok(privatePaths.every(p=>source!==p&&!source.startsWith(p+path.sep)&&!p.startsWith(source+path.sep)),`Private data reachable through ${mount}`);
   }
   const code=`const fs=require('fs');if(fs.readFileSync('/versions/selected.txt','utf8')!=='USER_SELECTED_SOURCE')throw Error('Missing selected material');if(${JSON.stringify([...privatePaths,'/objects','/control.sqlite'])}.some(p=>fs.existsSync(p)))throw Error('Library visible');if(${i}===0&&fs.readFileSync('/work/plugins/selected.mjs','utf8')!=='USER_SELECTED_SOURCE')throw Error('Selected workspace missing');console.log('selected-only');`;
   const output=execFileSync('docker',['run','--rm','--network','none',...options.mounts.flatMap(m=>['--mount',m]),base,'node','-e',code],{encoding:'utf8',timeout:60000});
   assert.match(output,/selected-only/);
  }
 }finally{fs.rmSync(root,{recursive:true,force:true})}
});
