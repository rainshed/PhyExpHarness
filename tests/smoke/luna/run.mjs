import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createChatGPTCredentials } from '../../../src/integrations/models/chatgpt_auth.mjs';
import { DshSession } from '../../../src/runtime/core/dsh_session.mjs';
import { validateLuna } from './validate.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const model = 'gpt-6-luna';
const provider = 'openai-codex';
const timeoutMs = 180_000;
const runId = `luna-${new Date().toISOString().replace(/[:.]/g, '-')}`;
const runDir = path.join(root, 'runs/smoke', runId);
const workspace = path.join(runDir, 'workspace');
const home = path.join(runDir, 'dsh-home');
fs.mkdirSync(workspace, { recursive: true });
fs.mkdirSync(home, { recursive: true });
const started = Date.now();
const summary = {
  runId, model, provider, reasoningEffort: 'medium', profile: 'sdk-minimal',
  dshVersion: JSON.parse(fs.readFileSync(path.join(root, 'node_modules/@deepseek-ai/dsh/package.json'))).version,
  status: 'running', runDir,
};
let credentials;
let session;
const redact = text => credentials ? credentials.redact(text) : String(text);
function saveSummary() {
  summary.elapsedSeconds = (Date.now() - started) / 1000;
  fs.writeFileSync(path.join(runDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
}

try {
  credentials = createChatGPTCredentials({ minimumValidityMs: timeoutMs + 60_000 });
  summary.authentication = credentials.description;
  const sessionId = `smoke-${crypto.randomUUID()}`;
  const challenge = { nonce: crypto.randomBytes(12).toString('hex'), values: Array.from({ length: 7 }, () => crypto.randomInt(100, 10000)) };
  fs.writeFileSync(path.join(workspace, 'challenge.json'), JSON.stringify(challenge) + '\n');
  const expected = { nonce: challenge.nonce, sum: challenge.values.reduce((a, b) => a + b, 0) };
  session = new DshSession({
    executable: path.join(root, 'node_modules/.bin/dsh'),
    patches: [path.join(root, 'src/runtime/profiles/luna-subscription.patch.yml')],
    workspace, home, environment: { PHYEXP_CREDENTIAL_FILE: credentials.credentialFile },
    rpcLog: path.join(runDir, 'rpc.jsonl'), stderrLog: path.join(runDir, 'stderr.log'), redact,
  });
  summary.launch = { executable: 'node_modules/.bin/dsh', args: session.args, sessionId };
  saveSummary();
  summary.initialize = await session.request('initialize', { cwd: workspace, provider, model, reasoningEffort: 'medium', maxTokens: 4096 });
  console.log('DeepSeek sdk-minimal initialized with openai-codex / gpt-6-luna');
  const prompt = 'Use your bash tool to read challenge.json in the current directory and compute the sum of its values. Do not inspect any other directory or environment variables, and do not use the network. After the tool returns, reply with ONLY a JSON object containing the nonce from the file and the numeric sum, with keys "nonce" and "sum". Do not guess the file contents.';
  fs.writeFileSync(path.join(runDir, 'prompt.txt'), prompt + '\n');
  const events = await session.prompt(sessionId, prompt, timeoutMs);
  fs.writeFileSync(path.join(runDir, 'events.json'), redact(JSON.stringify(events, null, 2)) + '\n');
  summary.eventTypes = [...new Set(events.map(event => event.type))];
  summary.expected = expected;
  summary.exit = await session.shutdown();
  Object.assign(summary, validateLuna(events, expected, summary.exit));
  summary.status = 'passed';
  saveSummary();
  console.log(`PASS: model → tool → model, answer verified, runtime exit 0. Evidence: ${runDir}`);
} catch (error) {
  summary.status = 'failed';
  summary.error = redact(error.message);
  saveSummary();
  console.error(summary.error);
  process.exitCode = 1;
} finally {
  try { await session?.dispose(); }
  finally { credentials?.dispose(); }
}
