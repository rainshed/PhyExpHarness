import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import net from 'node:net';
import path from 'node:path';
import { callContainer } from '../../src/integrations/quantum_harbor/container_tool.mjs';
import { DshSession } from '../../src/runtime/core/dsh_session.mjs';
import { resolveContainerPatch, verifyToolReceipt } from '../../src/integrations/quantum_harbor/profile.mjs';

test('container transport carries literal commands and propagates infrastructure errors', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'phyexp-tool-test-'));
  const socketPath = path.join(directory, 'exec.sock');
  let received;
  const server = net.createServer(socket => socket.once('data', data => {
    received = JSON.parse(data);
    socket.end(JSON.stringify(received.command === 'fail' ? { error: 'container unavailable' }
      : { stdout: 'verified', stderr: '', returnCode: 0 }));
  }));
  await new Promise(resolve => server.listen(socketPath, resolve));
  try {
    const command = 'printf "%s" "$(inside-container)"\n';
    assert.equal((await callContainer(socketPath, command)).stdout, 'verified');
    assert.deepEqual(received, { command });
    await assert.rejects(callContainer(socketPath, 'fail'), /container unavailable/);
  } finally {
    await new Promise(resolve => server.close(resolve));
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('MCP admission rejects missing task tools and unexpected host tools before model use', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'phyexp-mcp-inventory-'));
  const connections = [{ name: 'qsim', toolNames: ['list_devices', 'run_hamiltonian_probe_batch'] }];
  const write = tools => fs.writeFileSync(path.join(directory, 'tool-ready.json'), JSON.stringify({ tools }));
  try {
    const valid = ['bash', 'mcp__qsim__list_devices', 'mcp__qsim__run_hamiltonian_probe_batch', 'read_mcp_resource'];
    write(valid);
    assert.deepEqual(verifyToolReceipt(directory, connections).tools, valid);
    write(['bash', 'mcp__qsim__list_devices']);
    assert.throws(() => verifyToolReceipt(directory, connections), /inventory differs/);
    write([...valid, 'read_image']);
    assert.throws(() => verifyToolReceipt(directory, connections), /inventory differs/);
    write(['bash']);
    assert.throws(() => verifyToolReceipt(directory, connections), /inventory differs/);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

for (const model of ['gpt-6-luna', 'gpt-6-sol']) {
test(`real sdk-minimal admits ${model} and container bash without invoking a model`, async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'phyexp-startup-'));
  const credentialFile = path.join(directory, 'credentials.json');
  fs.writeFileSync(credentialFile, JSON.stringify({ version: 1, refs: {}, records: {} }));
  const session = new DshSession({ executable: path.resolve('node_modules/.bin/dsh'),
    workspace: directory, home: path.join(directory, 'home'),
    patches: [path.resolve('src/runtime/profiles/luna-subscription.patch.yml'), resolveContainerPatch(directory)],
    environment: { PHYEXP_CREDENTIAL_FILE: credentialFile, PHYEXP_HARBOR_SOCKET: path.join(directory, 'unused.sock'),
      PHYEXP_SOLVER_MODEL: model,
      PHYEXP_TOOL_RECEIPT: path.join(directory, 'tool-ready.json') },
    rpcLog: path.join(directory, 'rpc.jsonl'), stderrLog: path.join(directory, 'stderr.log') });
  try {
    await session.request('initialize', { cwd: directory, provider: 'openai-codex', model, reasoningEffort: 'medium' });
    verifyToolReceipt(directory);
    assert.equal(session.messages.some(m => m.params?.event?.type === 'assistant/message'), false);
    assert.deepEqual(await session.shutdown(), { code: 0, signal: null });
  } catch (error) {
    throw new Error(error.message + '\n' + (fs.existsSync(path.join(directory, 'stderr.log')) ? fs.readFileSync(path.join(directory, 'stderr.log'), 'utf8') : ''));
  } finally {
    await session.dispose();
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
}
