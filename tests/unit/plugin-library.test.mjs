import test from 'node:test';
import assert from 'node:assert/strict';
import {libraryWrites} from '@phyexp/meta-workbench-client/plugin-library';
const storage=()=>{const data=new Map();return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)}};
test('library deletion retries exactly after reload and cannot be overwritten by another intent',async()=>{
 const store=storage(),calls=[];let fail=true,keys=0;
 const request=async(route,body)=>{calls.push({route,body});if(fail)throw Error('lost response');return {state:'deleted'}};
 const first=libraryWrites(store,request,()=>String(++keys));
 await assert.rejects(first.send('/plugin-library/hash/change',{action:'delete',versions:[{id:'hash',revision:3}]}));
 await assert.rejects(first.send('/plugin-library/rescan',{}),/未确认/);
 fail=false;const restored=libraryWrites(store,request,()=>String(++keys));await restored.retry();
 assert.deepEqual(calls[0],calls[1]);assert.equal(keys,1);assert.equal(restored.pending(),null);
});
test('definitive revision conflict releases the pending key while jobs survive reload',async()=>{
 const store=storage();let conflict=true;
 const writes=libraryWrites(store,async()=>{if(conflict)throw Object.assign(Error('changed'),{status:409});return {jobId:'job-1'}},()=> 'key');
 await assert.rejects(writes.send('/plugin-library/hash/change',{}));assert.equal(writes.pending(),null);
 conflict=false;await writes.send('/plugin-library/rescan',{});assert.equal(store.getItem('phyexp:plugin-library:job'),'job-1');
});
test('an HTTP timeout keeps the original library write available for exact replay',async()=>{
 const store=storage();let timeout=true;const calls=[];
 const writes=libraryWrites(store,async(route,body)=>{calls.push({route,body});if(timeout)throw Object.assign(Error('timeout'),{status:408});return {state:'deleted'}},()=> 'timeout-key');
 await assert.rejects(writes.send('/plugin-library/hash/change',{action:'delete'}));assert.ok(writes.pending());
 timeout=false;await writes.retry();assert.deepEqual(calls[0],calls[1]);assert.equal(writes.pending(),null);
});
