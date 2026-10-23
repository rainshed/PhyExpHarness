// A frozen authentication handle, never a frozen access/refresh token or host path.
export function codexHostProfile(adapter,provider,profile){
 return adapter==='pi-ai'&&provider==='openai-codex'&&profile&&
  ['apiKeyEnv','api','baseURL'].every(key=>profile[key]==null)&&
  (profile.headers==null||typeof profile.headers==='object'&&!Array.isArray(profile.headers)&&Object.keys(profile.headers).length===0);
}
export function usesCodexHost(snapshot){
 if(snapshot.nativeAuth===undefined)return false;
 const profiles=snapshot.config?.providers;
 if(snapshot.nativeAuth!=='codex-host'||snapshot.credentialRef!=null||
  Object.keys(profiles||{}).length!==1||
  !codexHostProfile(snapshot.adapter,snapshot.call?.provider,profiles?.[snapshot.call?.provider]))
  throw new Error('Invalid native Codex host authentication binding');
 return true;
}
