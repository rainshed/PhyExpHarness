import net from 'node:net';

// Fixed endpoints come only from trusted task discovery, never from Runner requests.
export async function* forwardMcp(connections, payload, signal) {
  const target = connections.find(c => c.name === payload.name);
  if (!target || !['GET', 'POST', 'DELETE'].includes(payload.method)) throw new Error('MCP capability denied');
  const headers = {};
  for (const name of ['content-type', 'accept', 'mcp-session-id', 'mcp-protocol-version', 'last-event-id'])
    if (typeof payload.headers?.[name] === 'string') headers[name] = payload.headers[name];
  const response = await fetch(target.url, { method: payload.method, headers,
    body: payload.method === 'POST' ? payload.body : undefined, signal, redirect: 'error' });
  const returned = {};
  for (const name of ['content-type', 'mcp-session-id', 'mcp-protocol-version'])
    if (response.headers.has(name)) returned[name] = response.headers.get(name);
  yield {status: response.status, headers: returned};
  if (response.body) for await (const chunk of response.body) yield {bytes: Buffer.from(chunk).toString('base64')};
}

export function callContainer(socketPath, command, signal) {
  if (typeof command !== 'string' || Buffer.byteLength(command) > 1024 * 1024) throw new Error('Invalid command');
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath); let data = '';
    const abort = () => socket.destroy(new Error('Container command aborted'));
    const cleanup = () => signal?.removeEventListener('abort', abort);
    signal?.addEventListener('abort', abort, {once:true}); if (signal?.aborted) abort();
    socket.setTimeout(320000, () => socket.destroy(new Error('Container bridge timed out')));
    socket.on('connect', () => socket.write(JSON.stringify({command}) + '\n'));
    socket.on('data', chunk => { data += chunk; if (data.length > 32 * 1024 * 1024) socket.destroy(new Error('Container result too large')); });
    socket.on('error', error => {cleanup(); reject(error);});
    socket.on('end', () => {cleanup(); try {const result=JSON.parse(data); if(result.error)throw new Error(result.error); resolve(result);} catch(error){reject(error);} });
  });
}
