import readline from 'node:readline';
const root=process.argv[2];
const input=readline.createInterface({input:process.stdin});
input.on('line',async line=>{
 let row;try{
  row=JSON.parse(line);if(row.id===undefined)return;
  let result;
  if(row.method==='initialize')result={protocolVersion:row.params.protocolVersion,capabilities:{tools:{}},serverInfo:{name:'phyexp-task',version:'1'}};
  else if(row.method==='ping')result={};
  else if(row.method==='tools/list')result={tools:[{name:'task_bash',description:'Run a command in the official task container at /app. Task files and final submissions must be written here. Shell state resets; files persist.',inputSchema:{type:'object',properties:{command:{type:'string'}},required:['command'],additionalProperties:false}}]};
  else if(row.method==='tools/call'&&row.params.name==='task_bash'){
   if(typeof row.params.arguments?.command!=='string')throw new Error('command required');
   const response=await fetch(root+'/tool',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({command:row.params.arguments.command})});
   const value=await response.json();
   if(!response.ok)throw new Error('Task execution unavailable');
   result={content:[{type:'text',text:(value.stdout+'\n'+value.stderr).slice(0,32000)+'\n[exit '+value.returnCode+']'}],isError:value.returnCode!==0};
  }else throw new Error('Unknown MCP method');
  process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:row.id,result})+'\n');
 }catch(error){if(row?.id!==undefined)process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:row.id,error:{code:-32603,message:error.message}})+'\n');}
});
