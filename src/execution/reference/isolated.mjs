// Runs in the same network-none, read-only Runner boundary as the native Harness.
import fs from 'node:fs';
import http from 'node:http';
import readline from 'node:readline';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {cliLaunch} from './cli.mjs';
const config=JSON.parse(fs.readFileSync('/config/runner.json'));
const pending=new Map(),send=row=>process.stdout.write(JSON.stringify(row)+'\n');
const server=http.createServer(async(req,res)=>{
 const path=req.url.split('?')[0],mcp=path.startsWith('/mcp/')?path.slice(5):null;
 if(mcp&&!config.mcpConnections.some(c=>c.name===mcp)){res.writeHead(403).end();return;}
 if(!mcp&&req.method!=='POST'){res.writeHead(403).end();return;}
 const id=crypto.randomUUID();let complete=false,body='';
 res.on('close',()=>{pending.delete(id);if(!complete)send({method:'phyexp/cancel',params:{id}});});
 try{
  for await(const bytes of req){body+=bytes;if(Buffer.byteLength(body)>32*1024*1024)throw new Error('Oversized request');}
  const op=mcp?'mcp':path==='/tool'?'tool':'wire';
  const payload=op==='tool'?JSON.parse(body):mcp?{name:mcp,method:req.method,headers:req.headers,body}:{path,method:req.method,headers:req.headers,body};
  pending.set(id,row=>{
   if(row.error){if(!res.headersSent)res.writeHead(502,{'content-type':'application/json'});res.write(JSON.stringify({error:{type:'reference_gateway_error',message:row.error}}));}
   else if(row.result!==undefined){
    if(op==='tool'){if(!res.headersSent)res.writeHead(200,{'content-type':'application/json'});res.write(JSON.stringify(row.result));}
    else{if(row.result.status)res.writeHead(row.result.status,row.result.headers);if(row.result.bytes)res.write(Buffer.from(row.result.bytes,'base64'));}
   }
   if(row.done||row.error){complete=true;pending.delete(id);res.end();}
  });
  send({method:'phyexp/request',params:{id,operation:op,payload}});
 }catch(error){if(!res.headersSent)res.writeHead(400);res.end(JSON.stringify({error:error.message}));}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
fs.mkdirSync('/tmp/home',{recursive:true});fs.mkdirSync('/tmp/work',{recursive:true});
const launch=cliLaunch(config,server.address().port);
for(const dir of [launch.env.CODEX_HOME,launch.env.CLAUDE_CONFIG_DIR].filter(Boolean))fs.mkdirSync(dir,{recursive:true});
const child=spawn(launch.executable,launch.args,{cwd:'/tmp/work',env:launch.env,stdio:['pipe','pipe','inherit']});
child.stdin.end(launch.input);
const events=readline.createInterface({input:child.stdout});
events.on('line',line=>{if(Buffer.byteLength(line)>32*1024*1024){child.kill('SIGKILL');return;}
 try{send({method:'reference/event',params:JSON.parse(line)});}catch{send({method:'reference/output',params:{text:line}});}});
child.on('error',error=>{send({method:'reference/error',params:{message:error.message}});server.close();process.exitCode=1;});
child.on('exit',code=>{server.close();process.exit(code??1);});
const input=readline.createInterface({input:process.stdin});
input.on('line',line=>{try{const row=JSON.parse(line);if(row.method==='phyexp/response')pending.get(row.params.id)?.(row.params);}catch{child.kill('SIGTERM');}});
input.on('close',()=>child.kill('SIGTERM'));process.on('SIGTERM',()=>child.kill('SIGTERM'));
