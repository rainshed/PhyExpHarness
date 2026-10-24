import {appendLog} from '../host/log_store.mjs';
import fs from 'node:fs';
import readline from 'node:readline';
import { spawn } from 'node:child_process';

// One SDK session per process. DeepSeek owns the model/tool execution loop.
export class DshSession {
  constructor({ executable, profile = 'sdk-minimal', patches = [], workspace, home,
    environment = {}, rpcLog, stderrLog, redact = String, args, handleRequest }) {
    this.messages = [];
    this.pending = new Map();
    this.sequence = 0;
    this.turn = null;
    this.args = args ?? ['--profile', profile, ...patches.flatMap(patch => ['--patch', patch])];
    const allowedEnvironment = ['PATH', 'HOME', 'USER', 'SHELL', 'TMPDIR', 'LANG', 'LC_ALL',
      'SSL_CERT_FILE', 'NODE_EXTRA_CA_CERTS', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
      'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'];
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => allowedEnvironment.includes(key)));
    Object.assign(env, environment, { DSH_HOME: home, NO_COLOR: '1' });
    this.proc = spawn(executable, this.args, { cwd: workspace, env, stdio: ['pipe', 'pipe', 'pipe'] });
    this.exited = new Promise((resolve, reject) => {
      this.proc.once('error', error => {
        this.rejectPending(error);
        reject(error);
      });
      this.proc.once('exit', (code, signal) => {
        this.rejectPending(new Error(`Runtime exited: ${code ?? signal}`));
        resolve({ code, signal });
      });
    });
    this.exited.catch(() => {});
    this.proc.stdin.on('error', error => this.rejectPending(error));
    this.proc.stderr.on('data', chunk => {try{appendLog(stderrLog, redact(chunk));}catch(error){this.rejectPending(error);this.proc.kill('SIGTERM');}});
    this.lines = readline.createInterface({ input: this.proc.stdout });
    this.lines.on('line', line => {
      try{appendLog(rpcLog, redact(line) + '\n');}catch(error){this.rejectPending(error);this.proc.kill('SIGTERM');return;}
      let message;
      try { message = JSON.parse(line); } catch { return; }
      if (message.method === 'phyexp/request') {
        const { id, operation, payload } = message.params;
        const abort = new AbortController(); this.bridgeCalls ??= new Map();
        if (this.bridgeCalls.size >= 16 || this.bridgeCalls.has(id)) return this.proc.kill('SIGTERM');
        this.bridgeCalls.set(id, abort);
        const send = value => { if (this.proc.stdin.writable) this.proc.stdin.write(JSON.stringify({method:'phyexp/response',params:{id,...value}})+'\n'); };
        (async () => { try {
          if (!handleRequest) throw new Error('Gateway unavailable');
          for await (const result of handleRequest(operation, payload, abort.signal)) send({result});
          send({done:true});
        } catch(error) { send({error:error.gatewayFailure?.message||error.message,...(error.gatewayFailure?{failure:error.gatewayFailure}:{})}); }
        finally { this.bridgeCalls.delete(id); } })();
        return;
      }
      if (message.method === 'phyexp/cancel') { this.bridgeCalls?.get(message.params.id)?.abort(); return; }
      this.messages.push(message);
      if (message.id !== undefined && !message.method) {
        const waiter = this.pending.get(String(message.id));
        if (waiter) {
          clearTimeout(waiter.timer);
          this.pending.delete(String(message.id));
          if (message.error) waiter.reject(new Error(JSON.stringify(message.error)));
          else waiter.resolve(message.result);
        }
      }
      const turn = this.turn;
      if (!turn || message.params?.sessionId !== turn.sessionId) return;
      if (message.method === 'session.event' && message.params.event?.type === 'agent/inbox/spliced') turn.received = true;
      if (turn.received && message.method === 'session.status' && message.params.status === 'idle') turn.resolve();
    });
  }

  rejectPending(error) {
    // Capture the trusted host failure before cancelling model/bridge requests.
    // Their abort receipts describe cleanup, not the reason this Runner stopped.
    if(error.hostFailure)this.failure??=error.hostFailure;
    for (const waiter of this.pending.values()) {
      clearTimeout(waiter.timer);
      waiter.reject(error);
    }
    this.pending.clear();
    for (const controller of this.bridgeCalls?.values() || []) controller.abort();
    this.turn?.reject(error);
  }

  request(method, params = null, timeoutMs = 30_000) {
    const id = String(++this.sequence);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  }

  async prompt(sessionId, text, timeoutMs = 180_000) {
    if (this.turn) throw new Error('A prompt is already running');
    let timer;
    const idle = new Promise((resolve, reject) => {
      this.turn = { sessionId, received: false, resolve, reject };
      timer = setTimeout(() => reject(new Error('Model/tool turn timed out')), timeoutMs);
    });
    idle.catch(() => {});
    try {
      await this.request('session/prompt', { sessionId, contentBlocks: [{ type: 'text', text }] });
      await idle;
    } finally {
      clearTimeout(timer);
      this.turn = null;
    }
    return this.messages.filter(message => message.method === 'session.event'
      && message.params?.sessionId === sessionId).map(message => message.params.event);
  }

  async shutdown() {
    await this.request('shutdown', null, 15_000);
    let timer;
    try {
      return await Promise.race([this.exited, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('Runtime did not exit after shutdown')), 15_000);
      })]);
    } finally {
      clearTimeout(timer);
    }
  }

  async dispose() {
    for (const waiter of this.pending.values()) clearTimeout(waiter.timer);
    if (this.proc.exitCode === null && this.proc.signalCode === null) {
      this.proc.kill('SIGTERM');
      const timer = setTimeout(() => this.proc.kill('SIGKILL'), 5_000);
      try { await this.exited; } catch { /* Original startup error is reported by the caller. */ }
      finally { clearTimeout(timer); }
    }
    this.lines.close();
  }
}
