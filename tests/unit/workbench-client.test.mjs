import test from 'node:test';
import assert from 'node:assert/strict';
import {createDraftStore,createCommands,createRequest,LatestRequest,watchCampaign,defaults} from '@phyexp/meta-workbench-client';
import {numericConfig} from '@phyexp/meta-workbench-client/form';
const memory=()=>{const rows=new Map();return {rows,getItem:k=>rows.get(k)||null,setItem:(k,v)=>rows.set(k,v)}};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
const config={...defaults,name:'Fixture'};

test('legacy draft and uncertain create migrate together, while UI state stays independent',async()=>{
 const storage=memory(),signature=JSON.stringify(numericConfig(config));
 storage.setItem('phyexp-draft',JSON.stringify(config));storage.setItem('phyexp-campaign','existing');
 storage.setItem('phyexp-create-attempt',JSON.stringify({signature,key:'original'}));
 const before=[...storage.rows];const store=createDraftStore(storage,'studio',defaults,{legacy:true});
 assert.equal(store.read().selected,'existing');
 const other=createDraftStore(storage,'experimental',defaults);other.update({selected:'other',config:{...config,name:'Other'}});
 assert.equal(store.read().selected,'existing');assert.equal(store.read().config.name,'Fixture');
 let body;
 const commands=createCommands({store,makeKey:()=>assert.fail('must reuse key'),request:async(route,value)=>{body=value;throw Error('lost reply')}});
 await assert.rejects(commands.create(config,3),/lost reply/);assert.equal(body.idempotencyKey,'original');
 const reloaded=createDraftStore(storage,'studio',defaults,{legacy:true});
 await createCommands({store:reloaded,makeKey:()=>assert.fail('must survive reload'),request:async(route,value)=>{assert.equal(value.idempotencyKey,'original');return {id:'once'}}}).create(config,4);
 assert.equal(reloaded.read().attempt,null);
 assert.deepEqual(before.map(([k])=>[k,storage.getItem(k)]),before,'legacy input remains available');
 let next;
 await createCommands({store:reloaded,makeKey:()=> 'new-intent',request:async(route,value)=>{next=value;return {id:'twice'}}}).create(config,4);
 assert.equal(next.idempotencyKey,'new-intent');
});

test('incompatible stored drafts and failed persistence never silently create a new activity',async()=>{
 const storage=memory();storage.setItem('phyexp:ui:studio:state','{"version":99,"config":{}}');
 assert.throws(()=>createDraftStore(storage,'studio',defaults),/不兼容/);
 assert.equal(storage.getItem('phyexp:ui:studio:state'),'{"version":99,"config":{}}');
 const good=memory(),store=createDraftStore(good,'studio',defaults);good.setItem=()=>{throw Error('quota')};
 await assert.rejects(createCommands({store,request:()=>assert.fail('no POST before identity persists')}).create(config),/quota/);
});

test('commands keep revision, changed drafts get new keys, and conflicts are not retried',async()=>{
 const store=createDraftStore(memory(),'studio',defaults);let calls=[],seq=0;
 const commands=createCommands({store,makeKey:()=>String(++seq),request:async(route,body)=>{calls.push({route,body});throw Error('conflict')}});
 await assert.rejects(commands.create(config),/conflict/);
 await assert.rejects(commands.create({...config,name:'changed'}),/conflict/);
 assert.notEqual(calls[0].body.idempotencyKey,calls[1].body.idempotencyKey);
 await assert.rejects(commands.control({id:'c',revision:7},'pause'),/conflict/);
 assert.equal(calls.length,3);assert.equal(calls[2].body.expectedRevision,7);assert.equal(calls[2].body.action,'pause');
 assert.equal(await commands.limits({id:'c',revision:7,config},config),false);
});

test('late detail reads cannot overwrite newer results or reopen a closed panel',async()=>{
 const resource=new LatestRequest(),first=deferred(),second=deferred();let signal;
 const a=resource.run(s=>{signal=s;return first.promise}),b=resource.run(()=>second.promise);
 assert.equal(signal.aborted,true);second.resolve('current');assert.deepEqual(await b,{current:true,value:'current'});
 first.resolve('obsolete');assert.deepEqual(await a,{current:false});
 const third=deferred(),c=resource.run(()=>third.promise);resource.cancel();third.reject(Error('late failure'));
 assert.deepEqual(await c,{current:false});
});

test('poll cancellation drops pending reads, events resume by cursor, and no command is sent',async()=>{
 const calls=[],updates=[],gate=deferred();let block=false;
 const request=async(route,body,signal)=>{
  assert.equal(body,undefined);calls.push({route,signal});
  if(block)return gate.promise;
  if(route==='/models')return {schemaVersion:2,revision:1,models:[]};
  if(route==='/campaigns')return [{id:'c'}];
  if(route.includes('/events'))return route.endsWith('=0')?[{seq:1}]:[];
  return {id:'c'};
 };
 const sub=watchCampaign({id:'c',request,onData:v=>updates.push(v),onError:assert.fail,interval:60000});
 try{
  await sub.refresh();await sub.refresh();assert.equal(updates.length,2);assert.deepEqual(updates[1].events,[{seq:1}]);
  assert.ok(calls.some(c=>c.route.endsWith('after=1')));
  block=true;const pending=sub.refresh();sub.dispose();gate.resolve([]);await pending;
  assert.equal(updates.length,2);assert.ok(calls.every(c=>c.signal.aborted));
 }finally{sub.dispose()}
});

test('transport forwards abort and preserves backend errors without retrying',async()=>{
 const signal=new AbortController().signal;let calls=0;
 const request=createRequest({fetch:async(url,options)=>{calls++;assert.equal(url,'/phyexp/api/campaigns');assert.equal(options.signal,signal);assert.equal(options.method,'POST');return {ok:false,json:async()=>({error:'revision conflict'})}}});
 await assert.rejects(request('/campaigns',{},signal),/revision conflict/);assert.equal(calls,1);
});
