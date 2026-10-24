import {loadGoalDraft} from './goal.mjs';
import {createAttemptStorageKey} from './create-attempt.mjs';

// One envelope preserves the draft and the identity of an uncertain create together.
export function createDraftStore(storage,namespace,fallback,{legacy=false}={}){
 if(!/^[a-z][a-z0-9-]*$/.test(namespace))throw Error('Invalid UI storage namespace');
 const storageKey=`phyexp:ui:${namespace}:state`;
 const raw=storage.getItem(storageKey);
 let state;
 if(raw){
  state=JSON.parse(raw);
  if(state.version!==1||!state.config||typeof state.config!=='object')throw Error('工作台草稿格式不兼容，原始草稿已保留。');
  state={...state,config:{...fallback,...state.config}};
 }else{
  const attempt=legacy?JSON.parse(storage.getItem(createAttemptStorageKey)||'null'):null;
  state={version:1,config:legacy?loadGoalDraft(storage,fallback):{...fallback},selected:legacy?storage.getItem('phyexp-campaign')||'':'',attempt};
  storage.setItem(storageKey,JSON.stringify(state));
 }
 if(!state.attempt&&(Object.hasOwn(state.config,'softTokenLimit')||Object.hasOwn(state.config,'reserveTokens')||Object.values(state.config.referencePolicy?.limits||{}).some(v=>Object.hasOwn(v,'softTokenLimit')))){
  const backup=storageKey+':before-usage-removal';if(!storage.getItem(backup))storage.setItem(backup,JSON.stringify(state));
  delete state.config.softTokenLimit;delete state.config.reserveTokens;
  for(const value of Object.values(state.config.referencePolicy?.limits||{}))delete value.softTokenLimit;
  storage.setItem(storageKey,JSON.stringify(state));
 }
 return {
  read:()=>structuredClone(state),
  update(changes){const next={...state,...changes};storage.setItem(storageKey,JSON.stringify(next));state=next;return this.read();},
 };
}
