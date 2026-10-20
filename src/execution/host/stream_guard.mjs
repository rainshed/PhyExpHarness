import fs from 'node:fs';
export const DEFAULT_STREAM_POLICY=Object.freeze(JSON.parse(fs.readFileSync(new URL('./stream-policy.json',import.meta.url),'utf8')));

// Incremental JSON grammar: incomplete prefixes are allowed, impossible prefixes are not.
// No eval, no repeated reparsing of growing strings, and no retention of argument contents.
export class JsonPrefix {
 constructor(){this.stack=[];this.root='value';this.mode=null;this.escape=false;this.unicode=0;this.word='';this.literal='';this.key=false;}
 state(){return this.stack.at(-1)?.state||this.root;}
 value(){const top=this.stack.at(-1);if(top)top.state='commaOrEnd';else this.root='done';}
 error(){throw new Error('invalid_tool_arguments');}
 push(text){
  for(const c of text){
   if(this.mode==='string'){
    if(this.unicode){if(!/[0-9a-fA-F]/.test(c))this.error();this.unicode--;continue;}
    if(this.escape){this.escape=false;if(c==='u')this.unicode=4;else if(!'"\\/bfnrt'.includes(c))this.error();continue;}
    if(c==='\\'){this.escape=true;continue;}if(c==='"'){this.mode=null;if(this.key)this.stack.at(-1).state='colon';else this.value();continue;}
    if(c.charCodeAt(0)<32)this.error();continue;
   }
   if(this.mode==='literal'){
    this.word+=c;if(!this.literal.startsWith(this.word))this.error();
    if(this.word===this.literal){this.mode=null;this.value();}continue;
   }
   if(this.mode==='number'){
    if(/[0-9eE+.\-]/.test(c)){this.word+=c;continue;}
    if(!/^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?$/.test(this.word))this.error();
    this.mode=null;this.value();
   }
   if(' \n\r\t'.includes(c))continue;
   const state=this.state(),top=this.stack.at(-1);
   if(state==='done')this.error();
   if(state==='colon'){if(c!==':')this.error();top.state='value';continue;}
   if(state==='commaOrEnd'){
    if(c===','){top.state=top.kind==='object'?'key':'value';continue;}
    if(c===(top.kind==='object'?'}':']')){this.stack.pop();continue;}this.error();
   }
   if(state==='key'||state==='keyOrEnd'){
    if(c==='}'&&state==='keyOrEnd'){this.stack.pop();continue;}
    if(c!=='"')this.error();this.mode='string';this.key=true;continue;
   }
   if(state==='valueOrEnd'&&c===']'){this.stack.pop();continue;}
   if(!top&&c!=='{')this.error(); // Function arguments must be an object.
   if(c==='{'||c==='['){this.value();this.stack.push({kind:c==='{'?'object':'array',state:c==='{'?'keyOrEnd':'valueOrEnd'});if(this.stack.length>256)this.error();continue;}
   if(c==='"'){this.mode='string';this.key=false;continue;}
   if('tfn'.includes(c)){this.mode='literal';this.literal={t:'true',f:'false',n:'null'}[c];this.word=c;continue;}
   if(c==='-'||/[0-9]/.test(c)){this.mode='number';this.word=c;continue;}
   this.error();
  }
 }
 complete(){return this.root==='done'&&!this.stack.length&&!this.mode;}
}

export class StreamGuard {
 constructor(policy=DEFAULT_STREAM_POLICY,startedAt=Date.now()){
  this.policy={...DEFAULT_STREAM_POLICY,...policy};this.startedAt=startedAt;this.bytes=0;this.tools=new Map();this.textBytes=new Map();this.warnings=[];
 }
 fault(code,time,observed={}){return {schemaVersion:1,code,stage:'model',source:'trusted-model-gateway',detectedAt:new Date(time).toISOString(),
  policyVersion:this.policy.version,termination:'protection',observed:{responseBytes:this.bytes,
   responseContentBytes:this.bytes,responseBytesMeaning:'model-content-not-wire',...observed},limits:this.policy};}
 accept(chunk,time=Date.now()){
  let delta=chunk.type==='tool-call-delta'?chunk.argumentsDelta:chunk.type==='text-delta'||chunk.type==='reasoning-delta'?chunk.text:null;
  if(typeof delta==='string'){const n=Buffer.byteLength(delta);this.bytes+=n;
   if(chunk.type!=='tool-call-delta')this.textBytes.set(chunk.index,(this.textBytes.get(chunk.index)||0)+n);
  }
  if(chunk.type==='block-end'&&['text','reasoning'].includes(chunk.block?.type)){
   const n=Buffer.byteLength(chunk.block.text||'');this.bytes+=Math.max(0,n-(this.textBytes.get(chunk.index)||0));
  }
  if(this.bytes>this.policy.maxResponseBytes)return this.fault('response_size_limit',time);
  if(chunk.type==='tool-call-delta'){
   const key=chunk.index??chunk.id;let t=this.tools.get(key);
   if(!t){t={parser:new JsonPrefix(),bytes:0,white:0,whiteSince:null,tail:'',warned:false};this.tools.set(key,t);}
   const text=chunk.argumentsDelta||'';t.bytes+=Buffer.byteLength(text);
   if(t.bytes>this.policy.maxToolArgumentBytes)return this.fault('tool_argument_size_limit',time,{toolArgumentBytes:t.bytes});
   // Preserve the tail counter across arbitrary chunk boundaries.
   const nonwhite=/[^ \t\r\n]/.test(text),suffix=text.match(/[ \t\r\n]*$/)[0];
   if(nonwhite){t.white=Buffer.byteLength(suffix);t.whiteSince=suffix?time:null;}
   else if(text){t.white+=Buffer.byteLength(text);t.whiteSince??=time;}
   if(t.white>=this.policy.whitespaceMinBytes&&time-t.whiteSince>=this.policy.whitespaceMinMs)
    return this.fault('stream_whitespace',time,{consecutiveWhitespaceBytes:t.white,whitespaceDurationMs:time-t.whiteSince});
   try{t.parser.push(text);}catch{return this.fault('invalid_tool_arguments',time,{toolArgumentBytes:t.bytes});}
   t.tail=(t.tail+text).slice(-this.policy.repetitionWarningBytes);
   if(!t.warned&&t.tail.length===this.policy.repetitionWarningBytes){
    for(let period=1;period<=64;period++)if(t.tail.slice(period)===t.tail.slice(0,-period)){
     t.warned=true;this.warnings.push({code:'repetitive_tool_arguments',period,at:new Date(time).toISOString()});break;
    }
   }
  }
  if(chunk.type==='block-end'&&chunk.block?.type==='tool-call'){
   const t=this.tools.get(chunk.index);
   try{
    // Validate exact delivered arguments too; native adapters may normalize the end block.
    const value=JSON.parse(chunk.block.arguments);
    if(!value||Array.isArray(value)||typeof value!=='object'||(t&&!t.parser.complete()))throw new Error();
    if(!t){const n=Buffer.byteLength(chunk.block.arguments);this.bytes+=n;
     if(n>this.policy.maxToolArgumentBytes)return this.fault('tool_argument_size_limit',time,{toolArgumentBytes:n});
     if(this.bytes>this.policy.maxResponseBytes)return this.fault('response_size_limit',time);}
   }catch{return this.fault('invalid_tool_arguments',time);}
  }
  return null;
 }
}
