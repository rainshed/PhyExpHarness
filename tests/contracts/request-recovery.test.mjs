import test from 'node:test';import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';
import {isolatedSession} from '../../src/execution/host/isolation.mjs';
const model={provider:'openai-codex',model:'gpt-6-sol',reasoningEffort:'medium',maxTokens:8192};
const plugin=`import {defineTool} from '@deepseek-ai/dsh-tools';
export const name='recovery-fixture';export const inject=['tools'];
export function apply(ctx,config){let retries=0,calls=0;
 ctx.tools.register(defineTool({name:'count_once',description:'Count an irreversible fixture action.',parameters:{},output:{schema:{type:'string'},render:(_,v)=>[{type:'text',text:v}]},async execute(){return 'action-count-'+(++calls);}}));
 if(config.recover)ctx.on('agent/request-error',async (p,next)=>{
  if(!['SERVER','TRANSPORT'].includes(p.failure.code)||p.signal.aborted||retries++>=2)return next();
  if(!p.failure.requestId)throw Error('Missing gateway request identity');
  if(p.failure.code==='SERVER'&&p.failure.providerRetryAfterMs!==20)throw Error('Lost provider retry delay');
  return {kind:'retry'};
 });
}`;
for(const recover of [false,true])test('native isolated request recovery, plugin enabled='+recover,{timeout:45000},async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-native-recovery-'));const plugins=path.join(dir,'plugins');fs.mkdirSync(plugins);fs.writeFileSync(path.join(plugins,'fixture.mjs'),plugin);
 let calls=0;const settled=[];const reserves=[];
 const gateway=new ModelGateway({model,deadline:Date.now()+35000,audit:path.join(dir,'gateway.jsonl'),reserve:async id=>reserves.push(id),settle:async(id,r)=>settled.push({id,...r}),
  adapter:{async *stream(request){calls++;
   if(calls===1){yield {type:'finish',reason:{kind:'error',failure:{code:'PI_AI_ERROR',message:'Our servers are currently overloaded. Please try again later.',providerRetryAfterMs:20}}};return;}
   if(calls===2||calls===3){
    yield {type:'block-start',index:0,blockType:'tool-call'};
    yield {type:'tool-call-delta',index:0,id:'action-'+calls,name:'count_once',argumentsDelta:calls===2?'{}':'{"partial":'};
    if(calls===3)throw Error('WebSocket error');
    yield {type:'block-end',index:0,block:{type:'tool-call',id:'action-2',name:'count_once',arguments:'{}'}};
    yield {type:'finish',reason:{kind:'tool-calls'}};return;
   }
   const history=JSON.stringify(request.messages);assert.match(history,/action-count-1/);assert.ok(!history.includes('partial'));assert.ok(!history.includes('action-3'));
   yield {type:'block-start',index:0,blockType:'text'};yield {type:'text-delta',index:0,text:'completed'};yield {type:'block-end',index:0,block:{type:'text',text:'completed'}};
   yield {type:'usage',usage:{totalTokens:12,inputTokens:10,outputTokens:2}};yield {type:'finish',reason:{kind:'stop'}};
  }}});
 const session=isolatedSession({executionRoot:'src/execution',logs:dir,gateway,config:{disableLocalTools:true,fixedModel:model,modelInfo:{provider:model.provider,id:model.model,name:model.model,context:{contextWindow:272000},reasoning:{efforts:[{id:'medium',name:'Medium'}]}},plugins:[{id:'fixture',name:'/opt/phyexp/plugins/fixture.mjs',config:{recover}}]},mounts:[`type=bind,source=${plugins},target=/opt/phyexp/plugins,readonly`],async *handler(op){assert.equal(op,'receipt');yield {ok:true};}});
 try{await session.request('initialize',{...model,cwd:'/tmp/work'});
  const events=await session.prompt('recovery-fixture','Execute count_once once, then finish.',25000);const reason=events.filter(e=>e.type==='turn/end').at(-1).data.reason;
  assert.equal(calls,recover?4:1);assert.equal(reason.kind,recover?'completed':'error');
  assert.equal(events.filter(e=>e.type==='tool/call').length,recover?1:0);
  assert.equal(reserves.length,calls);assert.deepEqual(settled.map(r=>r.id),reserves);
  const summary=gateway.persistFinal({status:recover?'completed':'error',turnEnd:reason});
  if(recover){assert.equal(summary.failure,null);assert.equal(summary.requestRecovery.recoveredRequests,2);}
  else assert.equal(summary.failure.code,'model_service_overloaded');
  assert.equal(gateway.terminalFailure,null);await session.shutdown();
 }finally{await session.dispose();console.log('Request recovery evidence: '+dir);}
});
