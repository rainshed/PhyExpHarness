import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { DshSession } from '../runner/dsh_session.mjs';
export function isolatedSession({ executionRoot, logs, config, gateway, handler, mounts = [], image = 'phyexp-runner:0.2.1-rc.2' }) {
  const id = 'phyexp-runner-' + crypto.randomUUID();
  fs.mkdirSync(logs, { recursive: true });
  const configDir = path.join(logs,'runner-config'); fs.mkdirSync(configDir);
  fs.writeFileSync(path.join(configDir,'runner.json'), JSON.stringify(config));
  const args = ['run','--rm','-i','--init','--name',id,'--network','none','--read-only','--cap-drop','ALL',
    '--security-opt','no-new-privileges','--pids-limit','128','--memory','1g','--cpus','2',
    '--tmpfs','/tmp:rw,exec,nosuid,size=256m,mode=1777', '--tmpfs','/work:rw,nosuid,size=256m,mode=1777',
    '--mount',`type=bind,source=${path.resolve(executionRoot)},target=/opt/phyexp/src/execution,readonly`,
    '--mount',`type=bind,source=${path.resolve(configDir)},target=/config,readonly`];
  for (const key of ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']) args.push('--env',key+'=');
  for (const mount of mounts) args.push('--mount',mount);
  fs.writeFileSync(path.join(logs,'runner-identity.json'),JSON.stringify({container:id,image}));
  args.push(image,'/opt/phyexp/src/execution/runner/isolated.mjs');
  const session = new DshSession({executable:'docker',args,workspace:logs,home:logs,
    rpcLog:path.join(logs,'rpc.jsonl'),stderrLog:path.join(logs,'stderr.log'),
    async *handleRequest(operation,payload,signal) {
      if (operation === 'model') yield* gateway.stream(payload,signal);
      else if (handler) yield* handler(operation,payload,signal);
      else throw new Error('Capability unavailable');
    }});
  const dispose = session.dispose.bind(session);
  session.dispose = async () => { gateway.abort(); spawnSync('docker',['rm','-f',id],{stdio:'ignore',timeout:5000}); await dispose(); };
  return session;
}
