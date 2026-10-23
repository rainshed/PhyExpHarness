import { LlmAdapter, LlmError, resolveRetryPolicy } from '@deepseek-ai/dsh-llm';
import {recoveryPolicy,installRequestRecovery} from './request_recovery.mjs';
export const name = 'phyexp-model-gateway';
export const inject = ['llm','agents','sessionProjections'];
export async function* requestHost(operation, payload, signal) {
  const response = await fetch(process.env.PHYEXP_GATEWAY_URL + '/' + operation, {
    method: 'POST', body: JSON.stringify(payload), headers: { 'content-type': 'application/json' }, signal,
  });
  if (!response.ok) throw new Error(`Gateway refused: ${response.status}`);
  let buffer = ''; const decoder = new TextDecoder();
  for await (const bytes of response.body) {
    buffer += decoder.decode(bytes, {stream:true});
    if (buffer.length > 32 * 1024 * 1024) throw new Error('Oversized gateway frame');
    let end;
    while ((end = buffer.indexOf('\n')) >= 0) {
      const row = JSON.parse(buffer.slice(0, end)); buffer = buffer.slice(end + 1);
      if (row.error) throw row.failure?new LlmError(row.failure.message,row.failure.code,row.failure):new Error(row.error);
      yield row.result;
    }
  }
  if (buffer) throw new Error('Truncated gateway frame');
}
export function apply(ctx) {
  const info = JSON.parse(process.env.PHYEXP_MODEL_INFO);
  const policy=recoveryPolicy(JSON.parse(process.env.PHYEXP_REQUEST_RECOVERY||'null'));
  const recover=policy?installRequestRecovery(ctx,policy,Number(process.env.PHYEXP_RECOVERY_DEADLINE||'NaN')):null;
  const stream=options=>{const {signal,...data}=options;return requestHost('model',data,signal);};
  class RemoteAdapter extends LlmAdapter {
    providerRetryPolicy() { return resolveRetryPolicy({mode:'normal',maxRetries:0}); }
    providerInfo() { return { id: info.provider, name: info.provider }; }
    async listModels() { return [info]; }
    async resolveModel(provider, model) {
      if (provider !== info.provider || model !== info.id) throw new Error('Model unavailable');
      return info;
    }
    stream(options) { return recover&&options.purpose==='compaction'?recover(stream,options):stream(options); }
  }
  ctx.effect(() => ctx.llm.registerAdapter([info.provider], new RemoteAdapter()));
}
