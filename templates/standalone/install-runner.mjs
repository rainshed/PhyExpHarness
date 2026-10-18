import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
const root=path.dirname(fileURLToPath(import.meta.url));
const bundle=JSON.parse(fs.readFileSync(path.join(root,'bundle.json')));
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-runner-build-'));
try{
 for(const file of ['package.json','package-lock.json'])fs.copyFileSync(path.join(root,file),path.join(temp,file));
 fs.copyFileSync(path.join(root,'src/execution/runner/Dockerfile'),path.join(temp,'Dockerfile'));
 const result=spawnSync('docker',['build','-t',bundle.runnerImage,temp],{stdio:'inherit'});
 if(result.status!==0)throw new Error('Runner image installation failed');
}finally{fs.rmSync(temp,{recursive:true,force:true});}
