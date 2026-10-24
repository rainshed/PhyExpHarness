import fs from 'node:fs';
import path from 'node:path';
import {ModelGateway,hostFailureDiagnostics} from '../execution/host/model_gateway.mjs';
// A failed review must not poison its parent's model channel. All channels still
// share the exact model, provider, Campaign deadline and accounting callbacks.
export class MetaGateway {
 constructor({mainSessionId,...options}){this.mainSessionId=mainSessionId;this.options=options;this.channels=new Map();}
 stream(request,signal){
  const id=request.sessionId;if(typeof id!=='string'||!/^[-\w]+$/.test(id))throw new Error('Native session identity required');
  if(!this.channels.has(id)){
   const audit=id===this.mainSessionId?this.options.audit:path.join(path.dirname(this.options.audit),'review-sessions',id,'gateway-audit.jsonl');
   fs.mkdirSync(path.dirname(audit),{recursive:true});this.channels.set(id,new ModelGateway({...this.options,audit}));
  }
  return this.channels.get(id).stream(request,signal);
 }
 get firstFailure(){return this.channels.get(this.mainSessionId)?.firstFailure;}
 diagnostics(summary){return hostFailureDiagnostics(summary,this.channels.get(this.mainSessionId)?.diagnostics(summary)||{});}
 persistFinal(summary){
  const value=this.diagnostics(summary);const file=path.join(path.dirname(this.options.audit),'failure.json');
  fs.writeFileSync(file+'.tmp',(this.options.redact||String)(JSON.stringify({schemaVersion:2,...value},null,2))+'\n');fs.renameSync(file+'.tmp',file);return value;
 }
 abort(){for(const channel of this.channels.values())channel.abort();}
}
