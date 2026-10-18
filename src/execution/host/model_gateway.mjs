import fs from 'node:fs';
import crypto from 'node:crypto';
import { Context } from '@deepseek-ai/cordis';
import { LlmRuntime } from '@deepseek-ai/dsh-llm';
import LocalCredentials from '@deepseek-ai/dsh-credentials-local';
import * as PiAi from '@deepseek-ai/dsh-llm-pi-ai';

// The trusted caller owns route, deadline, accounting and credentials. Runner input owns none of them.
export class ModelGateway {
  constructor({ model, adapter, deadline, audit, reserve = async () => {}, settle = async () => {} }) {
    this.model = Object.freeze({ ...model }); this.adapter = adapter;
    this.deadline = deadline; this.audit = audit; this.reserve = reserve; this.settle = settle;
    this.active = new Map();
  }
  record(event) { fs.appendFileSync(this.audit, JSON.stringify({ time: new Date().toISOString(), ...event }) + '\n'); }
  async *stream(request, signal) {
    for (const key of ['provider', 'model', 'reasoningEffort', 'maxTokens']) {
      if (this.model[key] !== undefined && request[key] !== this.model[key]) {
        this.record({type:'rejected',reason:'fixed_model_mismatch',field:key});
        throw new Error(`Fixed model mismatch: ${key}`);
      }
    }
    if (Date.now() >= this.deadline) throw new Error('Run deadline reached');
    const id = crypto.randomUUID();
    await this.reserve(id, request);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort('Run deadline'), Math.max(1, this.deadline - Date.now()));
    this.active.set(id, controller);
    let usage = null, finish = null;
    const combined = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
    this.record({ type: 'request', id, request });
    try {
      for await (const chunk of this.adapter.stream({ ...request, signal: combined })) {
        if (combined.aborted) throw new Error('Model call cancelled');
        if (chunk.type === 'usage') usage = chunk.usage;
        if (chunk.type === 'finish') finish = chunk.reason;
        this.record({ type: 'chunk', id, chunk });
        yield chunk;
      }
      if (!finish) throw new Error('Model stream ended without terminal finish');
    } finally {
      clearTimeout(timeout); this.active.delete(id);
      this.record({ type: 'settled', id, usage, finish, usageStatus: usage && finish && finish.kind!=='error' ? 'reported' : 'unknown' });
      await this.settle(id, { usage, finish });
    }
  }
  abort() { for (const controller of this.active.values()) controller.abort('Supervisor cancelled'); }
}

export async function providerRuntime({ model, credentialFile }) {
  const ctx = new Context();
  try {
    await ctx.plugin(LlmRuntime).await();
    await ctx.plugin(LocalCredentials, { path: credentialFile, watch: false }).await();
    await ctx.plugin(PiAi, { providers: { [model.provider]: { models: [{ id: model.model }],
      retryPolicy: { mode: 'normal', maxRetries: 0 } } } }).await();
    const info = await ctx.llm.resolveModelInfo(model.provider, model.model);
    return { info, stream: request => ctx.llm.stream(request), dispose: () => ctx.fiber.dispose() };
  } catch (error) { await ctx.fiber.dispose(); throw error; }
}
