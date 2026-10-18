// Start the real minimal profile and exercise read-only MCP without model calls.
import fs from 'node:fs';
import path from 'node:path';
import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client';
import { DshSession } from '../../../src/runtime/core/dsh_session.mjs';
import { resolveContainerPatch, verifyToolReceipt } from '../../../src/integrations/quantum_harbor/profile.mjs';

const logs = path.resolve(process.argv[2]);
const connections = JSON.parse(fs.readFileSync(path.join(logs, 'mcp-connections.json')));
const credentialFile = path.join(logs, 'empty-credentials.json');
fs.writeFileSync(credentialFile, JSON.stringify({ version: 1, refs: {}, records: {} }));
const session = new DshSession({ executable: path.resolve('node_modules/.bin/dsh'),
  workspace: logs, home: path.join(logs, 'dsh-home'),
  patches: [path.resolve('src/runtime/profiles/luna-subscription.patch.yml'), resolveContainerPatch(logs)],
  environment: { PHYEXP_CREDENTIAL_FILE: credentialFile, PHYEXP_HARBOR_SOCKET: path.join(logs, 'unused.sock'),
    PHYEXP_SOLVER_MODEL: 'gpt-6-sol',
    PHYEXP_MCP_CONNECTIONS: path.join(logs, 'mcp-connections.json'),
    PHYEXP_TOOL_RECEIPT: path.join(logs, 'tool-ready.json') },
  rpcLog: path.join(logs, 'rpc.jsonl'), stderrLog: path.join(logs, 'stderr.log') });
try {
  await session.request('initialize', { cwd: logs, provider: 'openai-codex', model: 'gpt-6-sol', reasoningEffort: 'medium' });
  const receipt = verifyToolReceipt(logs, connections);
  const calls = [];
  for (const connection of connections) {
    const client = new Client({ name: 'phyexp-transport-preflight', version: '1.0.0' },
      { capabilities: {}, versionNegotiation: { mode: 'auto' } });
    try {
      await client.connect(new StreamableHTTPClientTransport(new URL(connection.url)));
      const result = await client.callTool({ name: 'list_devices', arguments: {} });
      if (result.isError) throw new Error('Read-only MCP call failed');
      calls.push({ server: connection.name, result });
    } finally { await client.close(); }
  }
  if (session.messages.some(m => m.params?.event?.type === 'assistant/message')) throw new Error('Unexpected model invocation');
  const exit = await session.shutdown();
  if (exit.code !== 0) throw new Error('Unclean shutdown');
  fs.writeFileSync(path.join(logs, 'mcp-preflight.json'), JSON.stringify({ status: 'passed',
    modelCalls: 0, tools: receipt.tools, calls }, null, 2));
  console.log(JSON.stringify({ status: 'passed', modelCalls: 0, tools: receipt.tools }));
} finally { await session.dispose(); }
