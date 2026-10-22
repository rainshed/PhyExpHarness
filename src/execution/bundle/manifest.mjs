// Python and Node entry points use the same stdlib-only, non-executing resolver.
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

export function resolveBundle(root) {
  const result = spawnSync(process.env.PHYEXP_PYTHON || 'python3',
    [fileURLToPath(new URL('./manifest.py', import.meta.url)), root],
    {encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, timeout: 30000});
  if (result.error || result.status !== 0)
    throw new Error('Frozen composition verification failed: ' + (result.error?.message || result.stderr));
  return JSON.parse(result.stdout);
}

export function pluginMounts(resolved) {
  return Object.entries(resolved.pluginRoots).map(([name, source]) =>
    `type=bind,source=${source},target=/opt/phyexp/plugins/${name},readonly`);
}
