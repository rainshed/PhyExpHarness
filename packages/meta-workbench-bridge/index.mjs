import {captureNativeModels} from './reference-native.mjs';
export const name='phyexp-meta-workbench-bridge';
export const inject=['webServer','connection'];
export function apply(ctx){
 const base=process.env.PHYEXP_CONTROL_URL,token=process.env.PHYEXP_USER_TOKEN;
 if(!base||!token)throw new Error('Workbench requires an independently running control service and user credential');
 ctx.effect(()=>ctx.webServer.register({kind:'prefix',path:'/phyexp/api',async handler(req,res){
  try{
   const rejection=ctx.connection.requestRejection(req);
   if(rejection){
    res.writeHead(rejection,{'content-type':'application/json','cache-control':'no-store'}).end(JSON.stringify({error:rejection===401?'请通过工作台启动链接登录后重试':'Request refused'}));return;
   }
   const origin=req.headers.origin;
   if((origin&&new URL(origin).host!==req.headers.host)||req.headers['sec-fetch-site']==='cross-site'){
    res.writeHead(403).end('Origin refused');return;
   }
   if(!['GET','POST'].includes(req.method)){res.writeHead(405).end();return;}
   if(req.method==='POST'&&!origin){res.writeHead(403).end('Origin required');return;}
   const parsed=new URL(req.url,'http://localhost');
   const route=parsed.pathname.slice('/phyexp/api'.length);
   if(req.method==='GET'&&route==='/references/catalog'){
    const snapshot=await captureNativeModels(ctx);
    const sync=await fetch(base+'/reference-native-sync',{method:'POST',headers:{authorization:`Bearer ${token}`,'content-type':'application/json'},body:JSON.stringify(snapshot),signal:AbortSignal.timeout(20000)});
    if(!sync.ok)throw new Error('Native model snapshot synchronization failed');
   }
   if(!/^\/(plugin-library|storage|references|health|tasks|campaigns|candidates|batches|trials|evidence|reports|exports|models|providers|provider-tests|meta-questions)(\/[-a-zA-Z0-9_]+)*$/.test(route)){
    res.writeHead(400).end('Invalid route');return;
   }
   let body='';for await(const chunk of req){body+=chunk;if(Buffer.byteLength(body)>1024*1024)throw new Error('Request too large');}
   // Control can verify many frozen images and provider endpoints before it
   // commits. A UI timeout does not cancel that controller-side operation.
   const control=req.method==='POST'&&/^\/campaigns\/[-a-zA-Z0-9_]+\/control$/.test(route);
   const deletion=/^\/campaigns\/[-a-zA-Z0-9_]+\/deletion$/.test(route);
   const response=await fetch(base+route+parsed.search,{method:req.method,headers:{authorization:`Bearer ${token}`,'content-type':'application/json'},
    body:req.method==='POST'?body:undefined,signal:AbortSignal.timeout(control||deletion?120000:20000)});
   const headers={'content-type':response.headers.get('content-type')||'application/json','cache-control':'no-store'};
   if(response.headers.has('content-disposition'))headers['content-disposition']=response.headers.get('content-disposition');
   const contents=Buffer.from(await response.arrayBuffer());
   res.writeHead(response.status,headers);
   res.end(contents);
  }catch(error){
   const timedOut=error.name==='TimeoutError';
   const message=timedOut?(req.method==='POST'
    ?'等待后台响应超时，操作结果尚未确认，后台可能仍在处理。请刷新查看活动状态，确认前不要重复提交。'
    :'读取后台状态超时，请稍后刷新。'):error.message;
   res.writeHead(timedOut?504:503,{'content-type':'application/json','cache-control':'no-store'}).end(JSON.stringify({error:message,connection:'unavailable',...(timedOut?{code:'control_response_timeout'}:{})}));
  }
 }}));
}
