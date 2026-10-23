import {api,key} from './transport.mjs';
export const defaultReferencePolicy=()=>({version:'meta-reference-v1',modelEnabled:false,harnessEnabled:false,modelRefs:[],harnessRefs:[],selectionMode:'meta-select',pairs:[],limits:{},catalogRevision:'unavailable'});
export function referenceError(p){
 if(!p)return '';
 if(p.modelEnabled&&!p.modelRefs?.length)return '请至少选择一个来自 DeepSeek Harness 配置的参考模型。';
 if(p.harnessEnabled&&!p.harnessRefs?.length)return '请至少选择一个参考 Harness。';
 if(p.modelEnabled&&p.harnessEnabled&&p.selectionMode==='pinned-pairs'&&!p.pairs?.length)return '请至少指定一个参考组合。';
 return '';
}
export function toggleReference(p,field,id){
 const next={...p,[field]:p[field].includes(id)?p[field].filter(x=>x!==id):[...p[field],id]};
 next.pairs=next.pairs.filter(pair=>next.modelRefs.includes(pair.modelRef)&&next.harnessRefs.includes(pair.harnessRef));return next;
}
export const readReferenceCatalog=()=>api('/references/catalog');
export const saveReferencePolicy=(campaign,policy,expectedRevision,stopRunning=false)=>api('/campaigns/'+campaign+'/references',{policy,idempotencyKey:key(),expectedRevision,stopRunning});
export const cancelReferenceBatch=(campaign,batchId,expectedPolicyRevision)=>api('/campaigns/'+campaign+'/references/cancel',{batchId,expectedPolicyRevision,idempotencyKey:key()});
