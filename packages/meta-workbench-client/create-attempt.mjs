// An unchanged retry must replay the same server command, including after reload
// or a lost response. A changed configuration represents a new create request.
export const createAttemptStorageKey='phyexp-create-attempt';
const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
export function sameCreateConfig(config,previous){
 try{return !!previous?.key&&canonical(config)===canonical(JSON.parse(previous.signature));}catch{return false;}
}
export function createAttempt(config,previous,makeKey){
 const signature=JSON.stringify(config);
 return sameCreateConfig(config,previous)&&typeof previous.key==='string'
  ?previous:{signature,key:makeKey()};
}
