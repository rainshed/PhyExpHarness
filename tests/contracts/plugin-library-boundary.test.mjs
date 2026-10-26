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
  fs.writeFileSync(path.join(filesRoot,'versions/selected.txt'),'USER_SELECTED_SOURCE');
  const frozen={id:'fixture',composition:JSON.parse(fs.readFileSync('packages/meta-harness/composition-native.json')),systemPrompt:{text:'fixture'},reviewerPrompt:'fixture'};
  const base=JSON.parse(fs.readFileSync('templates/harness/default/harness.json')).build.image;
  const captured=[];
  const host=new MetaHost({root:path.resolve('.'),logs:path.join(root,'logs'),frozen,config:{id:'fixture',model:{},workRoot,pluginWorkspace,sessionRoot:path.join(root,'activity/session'),filesRoot},sessionFactory:options=>{captured.push(options);return {}}});
  host.create('main','meta');host.create('review','reviewer');
  for(const [i,options] of captured.entries()){
   assert.ok(options.mounts.every(m=>!m.includes('source='+root+',')&&!m.includes('source='+path.join(root,'catalog'))));
   const code=`const fs=require('fs');if(fs.readFileSync('/versions/selected.txt','utf8')!=='USER_SELECTED_SOURCE')throw Error('Missing selected material');if(fs.existsSync(${JSON.stringify(path.join(root,'catalog'))})||fs.existsSync('/objects')||fs.existsSync('/control.sqlite'))throw Error('Library visible');if(${i}===0&&fs.readFileSync('/work/plugins/selected.mjs','utf8')!=='USER_SELECTED_SOURCE')throw Error('Selected workspace missing');console.log('selected-only');`;
   const output=execFileSync('docker',['run','--rm','--network','none',...options.mounts.flatMap(m=>['--mount',m]),base,'node','-e',code],{encoding:'utf8',timeout:60000});
   assert.match(output,/selected-only/);
  }
 }finally{fs.rmSync(root,{recursive:true,force:true})}
});
