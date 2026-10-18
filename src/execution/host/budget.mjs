// Per-run watchdog remains effective without a UI/control connection. Platform admission is fail-closed.
export function budgetGate({deadline,softTokenLimit=Infinity,requestReserve=300000,url,token,purpose='solver'}) {
 if(softTokenLimit===null)softTokenLimit=Infinity;
 const active=new Map();let confirmed=0,unknown=0;
 async function send(action,data){
  if(!url)return;
  const response=await fetch(url+'/'+action,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+token},
   body:JSON.stringify({purpose,...data}),signal:AbortSignal.timeout(10000)});
  if(!response.ok)throw new Error('Accounting admission unavailable: '+response.status);
 }
 return {
  async reserve(id){
   if(Date.now()>=deadline)throw new Error('Deadline reached');
   if(confirmed+unknown+[...active.values()].reduce((a,b)=>a+b,0)+requestReserve>softTokenLimit)throw new Error('Soft token threshold reached');
   active.set(id,requestReserve);
   try{await send('reserve',{id,reservedTokens:requestReserve});}catch(error){active.delete(id);throw error;}
  },
  async settle(id,result){
   const reserve=active.get(id)||requestReserve;active.delete(id);
   const tokens=result.usage?.totalTokens;
   if(Number.isFinite(tokens))confirmed+=tokens;
   if(!result.finish||result.finish.kind==='error'||!Number.isFinite(tokens))unknown+=reserve;
   await send('settle',{id,confirmedTokens:Number.isFinite(tokens)?tokens:null,unknown:!result.finish||result.finish.kind==='error'||!Number.isFinite(tokens)});
  },
  snapshot:()=>({confirmedTokens:confirmed,unknownReservedTokens:unknown,inflightReservedTokens:[...active.values()].reduce((a,b)=>a+b,0),limitKind:'soft',softTokenLimit:Number.isFinite(softTokenLimit)?softTokenLimit:null}),
 };
}
