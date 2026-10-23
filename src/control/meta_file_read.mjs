import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';

// The same read-only mounts visible to this Runner; no arbitrary host paths or
// another reviewer's private /outputs. Count Unicode code points, not JS UTF-16.
export async function readToolFile(filesRoot,outputRoot,{path:location,offset=0,limit=4096,sha256}={}){
 if(typeof location!=='string'||location.length>1024||!Number.isSafeInteger(offset)||offset<0||!Number.isSafeInteger(limit)||limit<1||limit>8192)throw new Error('Invalid file page; use offset >= 0 and limit 1..8192 characters');
 const match=/^\/(materials|evidence|sdk|versions|outputs)\/(.+)$/.exec(location);
 if(!match||match[2].split('/').some(p=>!p||p==='.'||p==='..'))throw new Error('Read an authorized absolute file path');
 const root=fs.realpathSync(match[1]==='outputs'?outputRoot:path.join(filesRoot,match[1]));
 const target=fs.realpathSync(path.join(root,match[2]));
 if(!target.startsWith(root+path.sep))throw new Error('File outside authorized mount');
 const handle=await fs.promises.open(target,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
 let total=0,text='';const digest=createHash('sha256'),decoder=new TextDecoder('utf-8',{fatal:true});
 try{
  if(!(await handle.stat()).isFile())throw new Error('Read a regular file');
  const consume=chunk=>{for(const c of chunk){if(total>=offset&&total<offset+limit)text+=c;total++;}};
  for await(const bytes of handle.createReadStream({autoClose:false})){digest.update(bytes);consume(decoder.decode(bytes,{stream:true}));}
  consume(decoder.decode());
 }finally{await handle.close();}
 const actual=digest.digest('hex');
 if(sha256!==undefined&&sha256!==actual)throw new Error('File changed; restart paging with the current SHA-256');
 return {path:location,sha256:actual,offset,offsetUnit:'characters',text,total,nextOffset:offset+limit<total?offset+limit:null};
}
