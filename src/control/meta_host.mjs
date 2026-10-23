import fs from 'node:fs';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import Ajv from 'ajv';
import {isolatedSession} from '../execution/host/isolation.mjs';
import {nativeEntries,presets} from '../../packages/meta-harness/composition-native.mjs';
import {reviewSchema} from '../../packages/meta-harness/stop-review.mjs';
import {MetaOutputs} from './meta_outputs.mjs';
import {readToolFile} from './meta_file_read.mjs';
const READ=new Set(['campaign_status','materials_list','materials_search','materials_read','evidence_list','evidence_read','sdk_search','sdk_read','sdk_inspect','research_list','research_read','evidence_excerpt']);
const validateReview=new Ajv().compile(reviewSchema);
// One activity research boundary (main + native children), separate stop-review boundary.
export class MetaHost{
 constructor({config,frozen,root,logs,api,gateway,modelInfo,image,sessionFactory=isolatedSession}){Object.assign(this,{config,frozen,root,logs,api,gateway,modelInfo,image,sessionFactory});this.children=new Map();this.runners=new Map();this.pendingReview=null;}
 runtime(action,input){return this.api('/meta-sessions/'+this.config.id+'/runtime',{action,input});}
 create(id,role,{outputSchema,reviewId,resume=false}={}){
  const {config}=this;
  const composition={...this.frozen.composition,plugins:this.frozen.composition.plugins.filter(p=>!p.package||config.referencePolicy?.[p.id==='meta-model-reference'?'modelEnabled':'harnessEnabled']!==false)};
  const logs=role==='meta'?this.logs:path.join(this.logs,'review-sessions',id);fs.mkdirSync(logs,{recursive:true});
  const childRoot=path.join(path.dirname(config.workRoot),'meta-children',id);
  const work=role==='meta'?config.workRoot:path.join(childRoot,'work');
  const sessionRoot=role==='meta'?config.sessionRoot:path.join(childRoot,'session');
  fs.mkdirSync(work,{recursive:true});fs.mkdirSync(sessionRoot,{recursive:true});
  const outputRoot=path.join(config.filesRoot,'outputs',role==='meta'?'main':id);const outputs=new MetaOutputs(outputRoot);
  const binding={id,role,reviewId,outputs,outputSchema,logs,agents:new Map()};
  const mounts=[`type=bind,source=${path.join(this.root,'packages/meta-harness')},target=/opt/phyexp/meta-plugin,readonly`,
   `type=bind,source=${work},target=/work`,`type=bind,source=${sessionRoot},target=/session`,
   ...['evidence','materials','sdk','versions'].map(name=>`type=bind,source=${path.join(config.filesRoot,name)},target=/${name},readonly`),
   `type=bind,source=${outputRoot},target=/outputs,readonly`,
   ...(role==='meta'?[`type=bind,source=${config.pluginWorkspace},target=/work/plugins`]:[]),
   ...composition.plugins.filter(p=>p.enabled&&p.package&&p.roles.includes(role)).map(p=>`type=bind,source=${path.join(this.root,'packages',p.package)},target=/opt/phyexp/optional-plugins/${p.package},readonly`)];
  const session=this.sessionFactory({executionRoot:path.join(this.root,'src/execution'),logs,image:this.image,
   gateway:{stream:(request,signal)=>{
    if(!binding.agents.has(request.sessionId))throw new Error('Model channel identity mismatch');return this.gateway.stream(request,signal);
   },abort:()=>{for(const agentId of binding.agents.keys())this.gateway.channels.get(agentId)?.abort();}},
   // Native cold resume uses route defaults for per-activation output limits.
   // Advertise the frozen cap there as well as on the initial SDK handshake.
   config:{nativeMeta:true,modelInfo:{...this.modelInfo,...(config.model.maxTokens!==undefined?{defaultMaxTokens:config.model.maxTokens}:{})},fixedModel:config.model,plugins:nativeEntries(composition,{role,systemPrompt:this.frozen.systemPrompt.text,reviewerPrompt:this.frozen.reviewerPrompt,compositionId:this.frozen.id,outputSchema})},mounts,
   handler:(op,payload,signal)=>this.handle(binding,op,payload,signal)});
  this.runners.set(id,{session,binding});return session;
 }
 async *handle(binding,operation,payload,signal){
  try{yield* this.dispatch(binding,operation,payload,signal);}
  catch(error){
   let file;
   try{file=binding.outputs.tool({name:payload.action,error:String(error),stack:error.stack});}
   catch{file={path:'/outputs/index.json',completeness:'partial'};}
   throw new Error(JSON.stringify({status:payload.action==='call'?'outcome_unknown':'failed',summary:error.message?.length<=200?error.message:'Host action failed; read the diagnostic file.',file}));
  }
 }
 async *dispatch(binding,operation,payload,signal){
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
  if(action==='file_read'){yield await readToolFile(this.config.filesRoot,outputs.root,input);return;}
  if(action==='register'){
   const research=role==='meta'&&input.preset===presets.research&&input.agentId!==id;
   if(typeof input.agentId!=='string'||!/^[-\w]+$/.test(input.agentId)||(!research&&(input.agentId!==id||input.preset!==presets[role])))throw new Error('Runner identity mismatch');
   if(research&&input.parentAgentId!==id)throw new Error('Research parent identity mismatch');
   if(binding.agents.has(input.agentId)&&binding.agents.get(input.agentId)!==input.preset)throw new Error('Registered role identity mismatch');
   const receipt=await this.runtime('register',{...input,reviewId:binding.reviewId,isolated:true,isolationScope:role==='meta'?'activity-research':'stop-review',runnerId:id});
   binding.agents.set(input.agentId,input.preset);yield receipt;return;
  }
  const actor=input.agentId??id;
  if(['observe','call'].includes(action)&&!binding.agents.has(actor))throw new Error('Unregistered Runner caller');
  if(action==='observe'){yield await this.runtime(action,{...input,agentId:actor});return;}
  if(action==='call'){
   if(binding.agents.get(actor)!==presets.meta&&!READ.has(input.operation))throw new Error('Read-only child role');
   yield await this.runtime('call',{...input,agentId:actor});return;
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
   const review=await this.runtime(action,{agentId:id,request:input.request});this.pendingReview=review;yield this.reviewReceipt(review);return;
  }
  if(action==='review_status'){
   yield this.reviewReceipt(await this.runtime(action,{agentId:id,reviewId:input.reviewId}));return;
  }
  if(action==='child_start'){
   if([...this.children.values()].filter(c=>!c.result).length>=2)throw new Error('Child capacity reached');
   const role=input.preset===presets.reviewer?'reviewer':null;
   if(!role)throw new Error('Unsupported child preset');
   const review=role==='reviewer'?this.pendingReview:null;
   if(role==='reviewer'&&(!review||review.state!=='pending'||review.replayed||[...this.children.values()].some(c=>c.reviewId===review.id)))throw new Error('No unconsumed stop review');
   const child={id:'child-'+randomUUID(),role,reviewId:review?.id};this.children.set(child.id,child);
   // Never use a parent's supplied reviewer schema/prompt as authoritative.
   child.promise=this.runChild(child,role==='reviewer'?[{type:'text',text:JSON.stringify(this.reviewReceipt(review))}]:input.prompt,role==='reviewer'?reviewSchema:input.outputSchema);
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
 reviewReceipt(review){
  // Reviewer receives the same immutable snapshot through its own read-only
  // materials mount; never interpolate that snapshot into a new model prompt.
  const data=JSON.stringify(review),sha=createHash('sha256').update(data).digest('hex');
  const folder=path.join(this.config.filesRoot,'materials','stop-reviews');fs.mkdirSync(folder,{recursive:true});
  const target=path.join(folder,sha+'.json');
  if(!fs.existsSync(target)){const temp=target+'.'+randomUUID();fs.writeFileSync(temp,data);fs.renameSync(temp,target);}
  if(createHash('sha256').update(fs.readFileSync(target)).digest('hex')!==sha)throw new Error('Published review integrity mismatch');
  return {id:review.id,state:review.state,replayed:!!review.replayed,summary:'Independent review snapshot and findings are in the file. Read it before deciding.',
   file:{path:'/materials/stop-reviews/'+sha+'.json',bytes:Buffer.byteLength(data),sha256:sha,completeness:'complete'}};
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
   result={output:[],stopReason:child.cancelled?'aborted':'error',diagnostic:String(error)};
   if(child.role==='reviewer')await this.runtime('review_failed',{reviewId:child.reviewId,error:String(error)}).catch(()=>{});
  }finally{try{await child.session?.dispose();binding?.outputs.dispose();}catch(error){result={...result,stopReason:'error',cleanupError:String(error)};}}
  try{
   const folder=path.join(this.config.filesRoot,'materials','agents',child.id);fs.mkdirSync(folder,{recursive:true});
   const artifacts=[];let bytes=0;
   const publish=(source,relative)=>{
    if(fs.lstatSync(source).isSymbolicLink())return;
    const stat=fs.statSync(source);if(!stat.isFile())return;
    if((bytes+=stat.size)>64*1024*1024)throw new Error('Child publication capacity exceeded; remaining files stay in its isolated workspace');
    const target=path.join(folder,relative);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(source,target);
    artifacts.push({path:'/materials/agents/'+child.id+'/'+relative,bytes:stat.size,sha256:createHash('sha256').update(fs.readFileSync(target)).digest('hex'),source:'child-generated',completeness:'complete'});
   };
   try{if(binding){
    for(const row of binding.outputs.entries.values())publish(path.join(binding.outputs.root,row.id+'.log'),'outputs/'+row.id+'.log');
    const work=path.join(path.dirname(this.config.workRoot),'meta-children',child.id,'work');
    const visit=(dir,rel='work')=>{for(const entry of fs.readdirSync(dir,{withFileTypes:true})){if(entry.isSymbolicLink())continue;const next=path.join(dir,entry.name),r=rel+'/'+entry.name;if(entry.isDirectory())visit(next,r);else publish(next,r);}};
    visit(work);
   }
   }catch(error){result.publicationError=String(error);}
   fs.writeFileSync(path.join(folder,'index.json'),JSON.stringify({id:child.id,artifacts,result}));
   result={stopReason:result.stopReason,output:[{type:'text',text:JSON.stringify({status:result.stopReason,childFiles:'/materials/agents/'+child.id+'/index.json',summary:'Complete child output and structured result are in the file.'})}]};
  }catch(error){
   let file;
   try{file=this.runners.get(this.config.id)?.binding.outputs.tool({name:'child_result',result,publicationError:String(error)});}
   catch{file={path:'/outputs/index.json',completeness:'partial'};}
   result={stopReason:'error',output:[{type:'text',text:JSON.stringify({status:'failed',summary:'Child result publication failed; inspect retained diagnostics.',file})}]};
  }
  child.result=result;
  return child.result;
 }
 async dispose(){for(const {session,binding} of this.runners.values()){await session.dispose();binding.outputs.dispose();}}
}
