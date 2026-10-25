import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {bridgeStream} from '../../src/execution/runner/bridge_stream.mjs';

test('admission wait immediately delivers headers and keepalives without completing the call', async () => {
  let response, closed = false;
  const server = http.createServer((req,res) => {
    response = res;
    bridgeStream(res, 10);
    res.once('close', () => { closed = true; });
  });
  await new Promise(r => server.listen(0,'127.0.0.1',r));
  try {
    const cancel = new AbortController();
    const request = await fetch(`http://127.0.0.1:${server.address().port}`, {signal:cancel.signal});
    assert.equal(request.status,200);
    assert.equal(response.writableEnded,false);
    const reader=request.body.getReader();
    assert.match(new TextDecoder().decode((await reader.read()).value), /"heartbeat":true/);
    response.end('{"result":{"type":"finish"}}\n');
    let remaining='';
    for (;;) { const row=await reader.read();if(row.done)break;remaining+=new TextDecoder().decode(row.value); }
    assert.match(remaining,/"type":"finish"/);
    assert.equal(closed,true);
  } finally { server.closeAllConnections(); await new Promise(r=>server.close(r)); }
});
