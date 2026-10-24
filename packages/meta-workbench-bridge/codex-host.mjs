// Host bridge readiness only. Never import an execution implementation or create
// a credential file here; the controller/runtime validates the frozen handle.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
export function codexHostProfile(adapter,provider,profile){
 return adapter==='pi-ai'&&provider==='openai-codex'&&profile&&
  ['apiKeyEnv','api','baseURL'].every(key=>profile[key]==null)&&
  (profile.headers==null||typeof profile.headers==='object'&&!Array.isArray(profile.headers)&&Object.keys(profile.headers).length===0);
}
export function codexHostAvailable(){
 try{
  const auth=JSON.parse(fs.readFileSync(process.env.PHYEXP_CODEX_AUTH_FILE||path.join(os.homedir(),'.codex/auth.json'),'utf8'));
  if(auth.auth_mode&&auth.auth_mode!=='chatgpt')return false;
  const claims=JSON.parse(Buffer.from(auth.tokens.access_token.split('.')[1],'base64url').toString());
  return Number.isFinite(claims.exp)&&claims.exp*1000>=Date.now()+240000;
 }catch{return false;}
}
