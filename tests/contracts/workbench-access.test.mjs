import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {setTimeout as delay} from 'node:timers/promises';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../../',import.meta.url));
const listen=server=>new Promise(resolve=>server.listen(0,'127.0.0.1',()=>resolve(server.address().port)));
const close=server=>new Promise(resolve=>server.close(resolve));
function request(port,url,headers={},method='GET',body=''){
 return new Promise((resolve,reject)=>{
  const req=http.request({hostname:'127.0.0.1',port,path:url,headers,method},res=>{
   let text='';res.on('data',chunk=>text+=chunk);res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,text}));
  });req.on('error',error=>reject(new Error(`${method} ${url.split('?')[0]}: ${error.message}`)));req.end(body);
 });
}

for(const variant of ['both','studio','classic'])test(`native ${variant} login protects workbench reads and commands behind an HTTPS proxy`, {timeout:30000},async()=>{
 const data=fs.mkdtempSync(path.join(os.tmpdir(),'phyexp-remote-'));
 const requests=[];
 const backend=http.createServer(async(req,res)=>{
  let body='';for await(const chunk of req)body+=chunk;
  requests.push({url:req.url,method:req.method,authorization:req.headers.authorization,body});
  res.writeHead(200,{'content-type':'application/json'}).end(JSON.stringify({ok:true}));
 });
 const backendPort=await listen(backend);
 const reserve=http.createServer();const port=await listen(reserve);await close(reserve);
 const authority='workbench.example:18443',origin='https://'+authority;
 fs.mkdirSync(path.join(data,'ui'));
 fs.writeFileSync(path.join(data,'user-token'),'fixture-only',{mode:0o600});
 fs.writeFileSync(path.join(data,'ui','workbench-access.json'),JSON.stringify({publicUrl:origin}));
 const env={...process.env,PHYEXP_DATA_DIR:data,PHYEXP_UI_HOME:path.join(data,'ui'),PHYEXP_USER_TOKEN:'fixture-only',
  PHYEXP_CONTROL_URL:`http://127.0.0.1:${backendPort}`,PHYEXP_UI_PORT:String(port),PHYEXP_UI_VARIANT:variant};
 delete env.PHYEXP_UI_PUBLIC_URL;
 const ui=spawn(process.execPath,['scripts/workbench.mjs'],{cwd:root,env,stdio:['ignore','pipe','pipe']});
 let output='';ui.stdout.on('data',chunk=>output+=chunk);ui.stderr.on('data',chunk=>output+=chunk);
 try{
  for(let i=0;i<150&&!output.includes('dsh web:');i++){assert.equal(ui.exitCode,null,'UI exited before startup');await delay(100);}
  const launch=output.match(/dsh web: (https:\/\/\S+)/)?.[1];assert.ok(launch,'UI must print the advertised login URL');
  const url=new URL(launch);assert.equal(url.origin,origin);
  const entries=JSON.parse(fs.readFileSync(path.join(data,'ui','workbench.patch.json'),'utf8'))[0].insert;
  assert.deepEqual(entries.map(p=>p.id),['phyexp-meta-workbench-bridge',...(variant==='studio'?[]:['phyexp-meta-workbench']),...(variant==='classic'?[]:['phyexp-meta-workbench-studio'])]);
  const headers={host:authority};
  assert.equal((await request(port,'/',headers)).status,401);
  for(const method of ['GET','POST'])assert.equal((await request(port,'/phyexp/api/campaigns',{...headers,origin},method,method==='POST'?'{}':'')).status,401);
  assert.equal((await request(port,'/phyexp/api/health',{host:'outside.example'})).status,403);
  assert.equal(requests.length,0);
  const login=await request(port,url.pathname+url.search,headers);
  assert.equal(login.status,303);
  const cookie=login.headers['set-cookie'][0].split(';')[0];
  const authenticated={...headers,cookie};
  assert.equal((await request(port,'/',authenticated)).status,200);
  assert.equal((await request(port,'/phyexp/api/health',authenticated)).status,200);
  assert.equal((await request(port,'/phyexp/api/campaigns',{...authenticated,origin,'content-type':'application/json'},'POST','{"fixture":true}')).status,200);
  assert.equal(requests.length,2);
  assert.equal(requests[1].body,'{"fixture":true}');
  assert.ok(requests.every(req=>req.authorization==='Bearer fixture-only'));
  assert.equal((await request(port,'/phyexp/api/campaigns',authenticated,'POST','{}')).status,403);
  assert.equal((await request(port,'/phyexp/api/campaigns',{...authenticated,origin:'https://outside.example'},'POST','{}')).status,403);
  assert.equal((await request(port,'/phyexp/api/health',{...authenticated,'sec-fetch-site':'cross-site'})).status,403);
  assert.equal((await request(port,'/phyexp/api/health',{...authenticated,cookie:cookie+'broken'})).status,401);
  assert.equal(requests.length,2,'denied requests must never reach the controller');
 }finally{
  if(ui.exitCode===null){const exited=once(ui,'exit');ui.kill('SIGTERM');await exited;}
  await close(backend);fs.rmSync(data,{recursive:true,force:true});
 }
});
