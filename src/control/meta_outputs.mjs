import {appendLog,readLogSync} from '../execution/host/log_store.mjs';
import fs from 'node:fs';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
export class MetaOutputs{
 constructor(root,{maxBytes=256*1024*1024}={}){
  this.root=root;this.maxBytes=maxBytes;this.bytes=0;this.entries=new Map();fs.mkdirSync(root,{recursive:true});
  const file=path.join(root,'index.json');
  if(fs.existsSync(file))for(const row of JSON.parse(fs.readFileSync(file)).items){
   if(!/^[a-zA-Z0-9-]{1,100}$/.test(row.id))throw new Error('Invalid saved output identity');
   const data=readLogSync(path.join(root,row.id+'.log'));const sha=createHash('sha256').update(data).digest('hex');
   if(row.status!=='live'&&(row.bytes!==data.length||row.sha256!==sha))throw new Error('Output integrity mismatch');
   this.bytes+=data.length;this.entries.set(row.id,{...row,bytes:data.length,sha256:sha,...(row.status==='live'?{status:'interrupted',completeness:'partial'}:{})});
  }
  this.publish();
 }
 publish(){const temp=path.join(this.root,'.index-'+randomUUID());fs.writeFileSync(temp,JSON.stringify({maxBytes:this.maxBytes,bytes:this.bytes,items:[...this.entries.values()].map(({sequence,...r})=>r)}));fs.renameSync(temp,path.join(this.root,'index.json'));}
 open(id,kind){
  if(!/^[a-zA-Z0-9-]{1,100}$/.test(id)||this.entries.has(id))throw new Error('Invalid/duplicate output ID');
  const row={id,kind,path:'/outputs/'+id+'.log',bytes:0,sequence:0,status:'live',completeness:'live'};
  fs.writeFileSync(path.join(this.root,id+'.log'),'',{flag:'wx'});this.entries.set(id,row);this.publish();return row;
 }
 append(id,sequence,bytes){
  const row=this.entries.get(id);if(!row||row.status!=='live'||row.sequence!==sequence)throw new Error('Output ordering/state mismatch');
  if(typeof bytes!=='string'||bytes.length>2*1024*1024)throw new Error('Output chunk too large');
  const data=Buffer.from(bytes,'base64');
  if(this.bytes+data.length>this.maxBytes){this.close(id,'capacity_exceeded');throw new Error('Output capacity exceeded; producer must stop. Partial bytes retained.');}
  appendLog(path.join(this.root,id+'.log'),data,{maxBytes:this.maxBytes});
  if(fs.existsSync(path.join(this.root,id+'.log.segments/index.json')))row.segments='/outputs/'+id+'.log.segments/index.json';row.bytes+=data.length;row.sequence++;this.bytes+=data.length;this.publish();return {bytes:row.bytes};
 }
 close(id,status){
  const row=this.entries.get(id);if(!row)throw new Error('Unknown output');if(row.status!=='live')return row;
  row.status=status;row.completeness=status==='complete'?'complete':'partial';row.sha256=createHash('sha256').update(readLogSync(path.join(this.root,id+'.log'))).digest('hex');this.publish();return row;
 }
 tool(value){const id=randomUUID();this.open(id,value.value?.receiptVersion==='meta-tool-receipt-v1'?'business-receipt':'tool-result');const data=Buffer.from(JSON.stringify(value));let sequence=0;for(let i=0;i<data.length;i+=64*1024)this.append(id,sequence++,data.subarray(i,i+64*1024).toString('base64'));return this.close(id,'complete');}
 dispose(){for(const row of this.entries.values())if(row.status==='live')this.close(row.id,'interrupted');}
}
