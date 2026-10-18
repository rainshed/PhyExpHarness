import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

export function resolveContainerPatch(logs, pluginPath = path.join(here, 'container_tool.mjs')) {
  // Loader package inventory reads plugin names before evaluating YAML !!js.
  const resolved = fs.readFileSync(path.join(here, 'container.patch.yml'), 'utf8')
    .replace('__PHYEXP_HARBOR_TOOL_PLUGIN__', JSON.stringify(pluginPath));
  const filename = path.join(logs, 'container.resolved.patch.yml');
  fs.writeFileSync(filename, resolved);
  return filename;
}

export function verifyToolReceipt(logs, connections = [], additionalTools = []) {
  const receipt = JSON.parse(fs.readFileSync(path.join(logs, 'tool-ready.json')));
  const required = ['bash', ...connections.flatMap(server => server.toolNames.map(name => `mcp__${server.name}__${name}`))];
  const resourceTools = ['list_mcp_resources', 'read_mcp_resource', 'list_mcp_resource_templates'];
  if (required.some(name => !receipt.tools.includes(name)) || receipt.tools.some(name =>
    !required.includes(name) && !additionalTools.includes(name) && !(connections.length && resourceTools.includes(name)))) {
    throw new Error('Model tool inventory differs from the task MCP discovery and container bash');
  }
  const stderr = path.join(logs, 'stderr.log');
  if (fs.existsSync(stderr) && fs.readFileSync(stderr, 'utf8').includes('disabling profile plugin row')) {
    throw new Error('DeepSeek disabled a required plugin; refusing to invoke a model');
  }
  return receipt;
}
