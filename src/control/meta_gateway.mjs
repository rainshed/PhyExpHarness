import fs from 'node:fs';
import path from 'node:path';
import {ModelGateway} from '../execution/host/model_gateway.mjs';
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
 diagnostics(summary){return this.channels.get(this.mainSessionId)?.diagnostics(summary)||{};}
 persistFinal(summary){return this.channels.get(this.mainSessionId)?.persistFinal(summary)||{};}
 abort(){for(const channel of this.channels.values())channel.abort();}
}
