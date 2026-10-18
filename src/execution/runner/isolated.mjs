// Runs inside --network none. Only loopback HTTP and bounded stdio connect to the trusted supervisor.
import fs from 'node:fs';
import http from 'node:http';
import readline from 'node:readline';
import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
const config = JSON.parse(fs.readFileSync('/config/runner.json', 'utf8'));
const pending = new Map();
const send = row => process.stdout.write(JSON.stringify(row) + '\n');
const server = http.createServer(async (req, res) => {
  const mcpName = req.url.startsWith('/mcp/') ? req.url.slice(5) : null;
  if (mcpName ? !config.mcpConnections?.some(c => c.name === mcpName) : req.method !== 'POST' || !['/model', '/tool', '/meta', '/receipt'].includes(req.url)) { res.writeHead(403).end(); return; }
  const id = crypto.randomUUID(); let data = '', complete = false;
  res.on('close', () => { pending.delete(id); if (!complete) send({ method: 'phyexp/cancel', params: { id } }); });
  try {
    for await (const part of req) { data += part; if (Buffer.byteLength(data) > 32 * 1024 * 1024) throw new Error('Request too large'); }
    const payload = mcpName ? {name:mcpName,method:req.method,headers:req.headers,body:data} : JSON.parse(data);
    if(!mcpName)res.writeHead(200, { 'content-type': 'application/x-ndjson' });
    pending.set(id, row => {
      if (row.error) { if(mcpName&&!res.headersSent) res.writeHead(502); res.write(JSON.stringify({ error: row.error }) + '\n'); }
      if (row.result !== undefined) {
        if(mcpName){if(row.result.status)res.writeHead(row.result.status,row.result.headers);if(row.result.bytes)res.write(Buffer.from(row.result.bytes,'base64'));}
        else res.write(JSON.stringify({ result: row.result }) + '\n');
      }
      if (row.done || row.error) { complete = true; pending.delete(id); res.end(); }
    });
    send({ method: 'phyexp/request', params: { id, operation: mcpName ? 'mcp' : req.url.slice(1), payload } });
  } catch (error) { res.end(JSON.stringify({ error: error.message }) + '\n'); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
fs.mkdirSync('/tmp/home', { recursive: true });
fs.mkdirSync('/tmp/work', { recursive: true });
const plugin = '/opt/phyexp/src/execution/runner/gateway_plugin.mjs';
const patch = [ { id: 'llm-deepseek', disabled: true }, { insert: [{ id: 'fixed-gateway', name: plugin }] },
  ...(config.disableLocalTools ? ['persistent-bash','persistent-pwsh','terminal-bash','terminal-pwsh','tool-fs','tool-working-directory'].map(id => ({ id, disabled: true })) : []),
  ...(config.plugins?.length ? [{ insert: config.plugins }] : []) ];
fs.writeFileSync('/tmp/gateway.patch.json', JSON.stringify(patch));
const connections=(config.mcpConnections||[]).map(c=>({...c,url:`http://127.0.0.1:${server.address().port}/mcp/${c.name}`}));
fs.writeFileSync('/tmp/mcp-connections.json',JSON.stringify(connections));
const child = spawn(process.execPath, ['/opt/phyexp/src/execution/runner/boot.mjs','/tmp/gateway.patch.json'], {
  cwd: '/tmp/work', env: { PATH: process.env.PATH, HOME: '/tmp/home', DSH_HOME: '/tmp/home/dsh', NO_COLOR:'1',
    PHYEXP_MODEL_INFO: JSON.stringify(config.modelInfo), PHYEXP_FIXED_MODEL: JSON.stringify(config.fixedModel), PHYEXP_GATEWAY_URL: `http://127.0.0.1:${server.address().port}`,
    PHYEXP_MCP_CONNECTIONS:'/tmp/mcp-connections.json',PHYEXP_TOOL_RECEIPT:'/tmp/tool-ready.json',...config.environment }, stdio: ['pipe','pipe','inherit'] });
const output = readline.createInterface({ input: child.stdout });
output.on('line', line => { if (Buffer.byteLength(line) < 32*1024*1024) process.stdout.write(line+'\n'); else child.kill('SIGKILL'); });
const input = readline.createInterface({ input: process.stdin });
input.on('line', line => {
  try { const row = JSON.parse(line); if (row.method === 'phyexp/response') pending.get(row.params.id)?.(row.params);
    else child.stdin.write(line+'\n'); } catch { child.kill('SIGKILL'); }
});
input.on('close', () => child.kill('SIGTERM'));
child.on('exit', code => { server.close(); process.exit(code ?? 1); });
process.on('SIGTERM', () => child.kill('SIGTERM'));
