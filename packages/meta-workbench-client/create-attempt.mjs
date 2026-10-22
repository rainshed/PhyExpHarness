// An unchanged retry must replay the same server command, including after reload
// or a lost response. A changed configuration represents a new create request.
export const createAttemptStorageKey='phyexp-create-attempt';
export function createAttempt(config,previous,makeKey){
 const signature=JSON.stringify(config);
 return previous?.signature===signature&&typeof previous.key==='string'&&previous.key
  ?previous:{signature,key:makeKey()};
}
