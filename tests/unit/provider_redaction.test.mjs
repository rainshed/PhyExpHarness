import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createProviderCredentials} from '../../src/execution/host/provider_auth.mjs';
import {ModelGateway} from '../../src/execution/host/model_gateway.mjs';

test('provider echoed credentials are redacted in audit chunks and failure files, including JSON escapes',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-redaction-'));
 const previous=process.env.PHYEXP_REDACTION_KEY,secret='private-"quoted-key';
 process.env.PHYEXP_REDACTION_KEY=secret;
 const model={provider:'fixture',model:'fixture'};
 const providerConfig={adapter:'pi-ai',api:'openai-completions',baseURL:'https://fixture.invalid',auth:{type:'api-key',env:'PHYEXP_REDACTION_KEY'},models:[{id:'fixture',reasoningEfforts:false}]};
 const credentials=createProviderCredentials(model,{providerConfig});
 try{
  const gateway=new ModelGateway({model,deadline:Date.now()+1000,audit:path.join(dir,'audit.jsonl'),redact:credentials.redact,
   adapter:{async *stream(){yield {type:'finish',reason:{kind:'error',error:'Invalid key: '+secret}};}}});
  for await(const _ of gateway.stream(model)){}
  const failed=new ModelGateway({model,adapter:null,deadline:Date.now()+1000,audit:path.join(dir,'audit.jsonl'),redact:credentials.redact});
  failed.fail({code:'fixture',message:secret});
  for(const name of ['audit.jsonl','failure.json']){
   const value=fs.readFileSync(path.join(dir,name),'utf8');
   assert.ok(!value.includes(secret));assert.ok(!value.includes(JSON.stringify(secret).slice(1,-1)));
   assert.match(value,/REDACTED/);
   for(const line of name==='audit.jsonl'?value.trim().split('\n'):[value])JSON.parse(line);
  }
 }finally{credentials.dispose();if(previous===undefined)delete process.env.PHYEXP_REDACTION_KEY;else process.env.PHYEXP_REDACTION_KEY=previous;fs.rmSync(dir,{recursive:true,force:true})}
});
