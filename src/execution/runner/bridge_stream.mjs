// Send headers immediately and keep the local transport alive while admission
// waits. Heartbeats are transport frames, never model output or extra requests.
export function bridgeStream(res, intervalMs = 15000) {
  res.writeHead(200, {'content-type':'application/x-ndjson'});
  res.flushHeaders();
  const timer = setInterval(() => {
    if (!res.destroyed && !res.writableEnded) res.write('{"heartbeat":true}\n');
  }, intervalMs);
  timer.unref();
  const close = () => clearInterval(timer);
  res.once('close', close);
  res.once('finish', close);
  return close;
}
