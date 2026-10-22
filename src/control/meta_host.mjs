import fs from 'node:fs';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import Ajv from 'ajv';
import {isolatedSession} from '../execution/host/isolation.mjs';
import {nativeEntries,presets} from '../../packages/meta-harness/composition-native.mjs';
import {reviewSchema} from '../../packages/meta-harness/stop-review.mjs';
import {MetaOutputs} from './meta_outputs.mjs';
const READ=new Set(['campaign_status','materials_list','materials_search','materials_read','evidence_list','evidence_read','sdk_search','sdk_read','sdk_inspect']);
const validateReview=new Ajv().compile(reviewSchema);
// One controller-authenticated host, distinct untrusted OS boundary per role.
export class MetaHost{
 constructor({config,frozen,root,logs,api,gateway,modelInfo,image}){Object.assign(this,{config,frozen,root,logs,api,gateway,modelInfo,image});this.children=new Map();this.runners=new Map();this.pendingReview=null;}
 runtime(action,input){return this.api('/meta-sessions/'+this.config.id+'/runtime',{action,input});}
 create(id,role,{outputSchema,reviewId,resume=false}={}){
  const {config}=this;
  const logs=role==='meta'?this.logs:path.join(this.logs,'review-sessions',id);fs.mkdirSync(logs,{recursive:true});
  const childRoot=path.join(path.dirname(config.workRoot),'meta-children',id);
  const work=role==='meta'?config.workRoot:path.join(childRoot,'work');
  const sessionRoot=role==='meta'?config.sessionRoot:path.join(childRoot,'session');
  fs.mkdirSync(work,{recursive:true});fs.mkdirSync(sessionRoot,{recursive:true});
  const outputRoot=path.join(config.filesRoot,'outputs',role==='meta'?'main':id);const outputs=new MetaOutputs(outputRoot);
  const binding={id,role,reviewId,outputs,outputSchema,logs};
  const mounts=[`type=bind,source=${path.join(this.root,'packages/meta-harness')},target=/opt/phyexp/meta-plugin,readonly`,
   `type=bind,source=${work},target=/work`,`type=bind,source=${sessionRoot},target=/session`,
   ...['evidence','materials','sdk','versions'].map(name=>`type=bind,source=${path.join(config.filesRoot,name)},target=/${name},readonly`),
   `type=bind,source=${outputRoot},target=/outputs,readonly`,
   ...(role==='meta'?[`type=bind,source=${config.pluginWorkspace},target=/work/plugins`]:[])];
  const session=isolatedSession({executionRoot:path.join(this.root,'src/execution'),logs,image:this.image,
   gateway:{stream:(request,signal)=>{
    if(request.sessionId!==id)throw new Error('Model channel identity mismatch');return this.gateway.stream(request,signal);
   },abort:()=>this.gateway.channels.get(id)?.abort()},
   config:{nativeMeta:true,modelInfo:this.modelInfo,fixedModel:config.model,plugins:nativeEntries(this.frozen.composition,{role,systemPrompt:this.frozen.systemPrompt.text,reviewerPrompt:this.frozen.reviewerPrompt,compositionId:this.frozen.id,outputSchema})},mounts,
   handler:(op,payload,signal)=>this.handle(binding,op,payload,signal)});
  this.runners.set(id,{session,binding});return session;
 }
 async *handle(binding,operation,payload,signal){
  if(operation==='receipt'){
   fs.writeFileSync(path.join(binding.logs,'bootstrap-receipt.json'),JSON.stringify({role:binding.role,compositionId:this.frozen.id,image:this.image,...payload}));
   yield {ok:true};return;
  }
  if(operation!=='meta')throw new Error('Unavailable Meta channel');
  const {action,input={}}=payload;const {id,role,outputs}=binding;
  if(action==='output_open'){yield outputs.open(input.id,input.kind);return;}
  if(action==='output_append'){yield outputs.append(input.id,input.sequence,input.bytes);return;}
  if(action==='output_close'){yield outputs.close(input.id,'complete');return;}
  if(action==='tool_output'){yield outputs.tool(input);return;}
  if(action==='register'){
   if(input.agentId!==id||input.preset!==presets[role])throw new Error('Runner identity mismatch');
   yield await this.runtime('register',{...input,agentId:id,preset:presets[role],reviewId:binding.reviewId,isolated:true});return;
  }
  if(action==='observe'){yield await this.runtime(action,{...input,agentId:id});return;}
  if(action==='call'){
   if(role!=='meta'&&!READ.has(input.operation))throw new Error('Read-only child role');
   yield await this.runtime('call',{...input,agentId:id});return;
  }
  if(action==='child_output'){
   if(role==='meta'||!binding.outputSchema||binding.structured)throw new Error('Structured output unavailable');
   if(!new Ajv({strict:false}).validate(binding.outputSchema,input.result))throw new Error('Invalid child result');
   binding.structured=input.result;yield {ok:true};return;
  }
  if(role!=='meta')throw new Error('Child cannot delegate or review');
  if(action==='user_question'){
   yield await this.runtime(action,{...input,agentId:id});return;
  }
  if(action==='review_request'){
   const review=await this.runtime(action,{agentId:id,request:input.request});this.pendingReview=review;yield review;return;
  }
  if(action==='review_status'){
   yield await this.runtime(action,{agentId:id,reviewId:input.reviewId});return;
  }
  if(action==='child_start'){
   if([...this.children.values()].filter(c=>!c.result).length>=2)throw new Error('Child capacity reached');
   const role=input.preset===presets.research?'research':input.preset===presets.reviewer?'reviewer':null;
   if(!role)throw new Error('Unsupported child preset');
   const review=role==='reviewer'?this.pendingReview:null;
   if(role==='reviewer'&&(!review||review.state!=='pending'||review.replayed||[...this.children.values()].some(c=>c.reviewId===review.id)))throw new Error('No unconsumed stop review');
   const child={id:'child-'+randomUUID(),role,reviewId:review?.id};this.children.set(child.id,child);
   // Never use a parent's supplied reviewer schema/prompt as authoritative.
   child.promise=this.runChild(child,role==='reviewer'?[{type:'text',text:JSON.stringify(review)}]:input.prompt,role==='reviewer'?reviewSchema:input.outputSchema);
   yield {id:child.id};return;
  }
  if(action==='child_status'||action==='child_cancel'){
   const child=this.children.get(input.id);if(!child)throw new Error('Unknown owned child');
   if(action==='child_cancel'&&!child.result){child.cancelled=true;await child.session?.dispose();}
   yield {id:child.id,result:child.result};return;
  }
  // In particular: no parent review_result, review_attach, register-reviewer,
  // model_request, credentials or arbitrary backend URLs are forwarded.
  throw new Error('Unavailable runtime action');
 }
 async runChild(child,prompt,outputSchema){
  let binding,result;
  try{
   child.session=this.create(child.id,child.role,{outputSchema,reviewId:child.reviewId});binding=this.runners.get(child.id).binding;
   await child.session.request('initialize',{...this.config.model,cwd:'/work'});
   const events=await child.session.prompt(child.id,JSON.stringify({task:prompt,evidenceIndex:'/evidence/index.json'}),Math.max(1,Math.min(300000,this.config.deadline*1000-Date.now())));
   const reason=events.filter(e=>e.type==='turn/end').at(-1)?.data.reason?.kind;
   if(reason!=='completed'||child.cancelled)throw new Error('Child did not complete');
   result={output:events.filter(e=>e.type==='assistant/message').at(-1)?.data.message?.content?.filter(b=>b.type==='text')||[],structured:binding.structured,stopReason:'completed'};
   if(outputSchema&&!binding.structured)throw new Error('Missing structured child result');
   if(child.role==='reviewer'){
    if(!validateReview(binding.structured))throw new Error('Invalid independent review');
    await this.runtime('review_attach',{reviewId:child.reviewId,childId:child.id});
    await this.runtime('review_result',{reviewId:child.reviewId,childId:child.id,result:binding.structured,stopReason:'completed'});
   }
  }catch(error){
   result={output:[],stopReason:child.cancelled?'aborted':'error',diagnostic:String(error).slice(0,4000)};
   if(child.role==='reviewer')await this.runtime('review_failed',{reviewId:child.reviewId,error:String(error)}).catch(()=>{});
  }finally{try{await child.session?.dispose();binding?.outputs.dispose();}catch(error){result={...result,stopReason:'error',cleanupError:String(error)};}}
  try{if(binding){
   const folder=path.join(this.config.filesRoot,'materials','agents',child.id);fs.mkdirSync(folder,{recursive:true});
   const artifacts=[];let bytes=0;
   const publish=(source,relative)=>{
    if(fs.lstatSync(source).isSymbolicLink())return;
    const stat=fs.statSync(source);if(!stat.isFile())return;
    if((bytes+=stat.size)>64*1024*1024)throw new Error('Child publication capacity exceeded; remaining files stay in its isolated workspace');
    const target=path.join(folder,relative);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(source,target);
    artifacts.push({path:'/materials/agents/'+child.id+'/'+relative,bytes:stat.size,sha256:createHash('sha256').update(fs.readFileSync(target)).digest('hex'),source:'child-generated',completeness:'complete'});
   };
   try{
    for(const row of binding.outputs.entries.values())publish(path.join(binding.outputs.root,row.id+'.log'),'outputs/'+row.id+'.log');
    const work=path.join(path.dirname(this.config.workRoot),'meta-children',child.id,'work');
    const visit=(dir,rel='work')=>{for(const entry of fs.readdirSync(dir,{withFileTypes:true})){if(entry.isSymbolicLink())continue;const next=path.join(dir,entry.name),r=rel+'/'+entry.name;if(entry.isDirectory())visit(next,r);else publish(next,r);}};
    visit(work);
   }catch(error){result.publicationError=String(error);}
   fs.writeFileSync(path.join(folder,'index.json'),JSON.stringify({id:child.id,artifacts,result}));
   result.output.push({type:'text',text:JSON.stringify({childFiles:'/materials/agents/'+child.id+'/index.json',publicationError:result.publicationError})});
  }}catch(error){result.publicationError=String(error);}
  child.result=result;
  return child.result;
 }
 async dispose(){for(const {session,binding} of this.runners.values()){await session.dispose();binding.outputs.dispose();}}
}
