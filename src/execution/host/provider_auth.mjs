import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createChatGPTCredentials} from './chatgpt_auth.mjs';
import {providerRoute} from './providers.mjs';

// Only trusted host workers call this bridge. Neither credential file nor environment enters Runner.
export function createProviderCredentials(model, options = {}) {
 const route=providerRoute(model,options.providerConfig);
 if(route.auth.type === 'codex') return createChatGPTCredentials(options);
 const ref=route.auth.env;
 const key=process.env[ref]?.trim();
 if(!key) throw new Error(ref+' is required in the host environment');
 if(key&&/[\r\n]/.test(key)) throw new Error('Invalid credential reference '+ref);
 const temp = fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-auth-'));
 const credentialFile = path.join(temp,'credentials.json');
 try {
  fs.chmodSync(temp,0o700);
  fs.writeFileSync(credentialFile,JSON.stringify({version:1,refs:{[ref]:key},records:{}}),{mode:0o600});
 } catch(error) { fs.rmSync(temp,{recursive:true,force:true});throw error; }
 return {credentialFile,description:'API key reference '+ref+'; host-only temporary credentials',
  redact:value=>[JSON.stringify(key).slice(1,-1),key].reduce((text,secret)=>text.split(secret).join('[REDACTED]'),String(value)),
  dispose:()=>fs.rmSync(temp,{recursive:true,force:true})};
}
