import LocalSubprocessRuntime from '@deepseek-ai/dsh-subprocess-local';
import {Transform} from 'node:stream';
import {randomUUID} from 'node:crypto';
import {channel} from './domain-control.mjs';
// Tee raw PTY bytes below the upstream terminal scrollback and tool preview caps.
// Backpressure reaches the producer; capture failure terminates it, never drops bytes.
export default class CapturedSubprocess extends LocalSubprocessRuntime{
 async spawnTerminal(spec){
  const handle=await super.spawnTerminal(spec);const id=randomUUID();let sequence=0;
  await channel('output_open',{id,kind:'terminal'});
  const output=new Transform({transform(chunk,_encoding,callback){
   channel('output_append',{id,sequence:sequence++,bytes:chunk.toString('base64')})
    .then(()=>callback(null,chunk)).catch(error=>{void handle.terminate();callback(error);});
  },flush(callback){channel('output_close',{id,status:'complete'}).then(()=>callback()).catch(callback);}});
  handle.output.on('error',error=>output.destroy(error));handle.output.pipe(output);
  return {pid:handle.pid,output,done:handle.done,write:handle.write.bind(handle),resize:handle.resize.bind(handle),
   inspectForeground:handle.inspectForeground.bind(handle),inspectActivity:handle.inspectActivity.bind(handle),
   signalForeground:handle.signalForeground.bind(handle),terminate:handle.terminate.bind(handle)};
 }
}
