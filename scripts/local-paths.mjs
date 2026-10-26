import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';

function canonical(value){
 try{return fs.realpathSync(value);}
 catch(error){
  if(!['ENOENT','ENOTDIR'].includes(error.code))throw error;
  const parent=path.dirname(value);
  return parent===value?value:path.join(canonical(parent),path.basename(value));
 }
}

// Keep this public launcher contract aligned with src/control/paths.py.
export function dataDirectory({env=process.env,platform=process.platform,home=os.homedir(),cwd=process.cwd()}={}) {
 const resolve=value=>canonical(path.resolve(cwd,value==='~'?home:value.startsWith('~/')?path.join(home,value.slice(2)):value));
 if(env.PHYEXP_DATA_DIR)return resolve(env.PHYEXP_DATA_DIR);
 if(platform==='darwin')return path.join(home,'Library/Application Support/PhyExpHarness');
 return path.join(resolve(env.XDG_DATA_HOME||path.join(home,'.local/share')),'PhyExpHarness');
}
