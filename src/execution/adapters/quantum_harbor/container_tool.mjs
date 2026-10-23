import fs from 'node:fs';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { apply as applyMcp, Config as McpConfig } from '@deepseek-ai/dsh-mcp-client';

export const name = 'phyexp-harbor-container';
export const inject = ['tools'];

export {callContainer} from '../../host/capabilities.mjs';
import {requestHost} from '../../runner/gateway_plugin.mjs';

export async function apply(ctx, _config, transport) {

  const limit = Number(process.env.PHYEXP_MAX_OUTPUT_CHARS || 16000);
  ctx.tools.register(defineTool({
    name: process.env.PHYEXP_TASK_TOOL_NAME || 'bash',
    description: 'Run a command in the Quantum-Harbor main task container. Each call starts a fresh bash shell in /app: files persist, but cd, variables and functions do not persist between calls. Commands have a 300-second limit. Use scripts to process large data and avoid printing large outputs. The host filesystem and Docker control socket are not available.',
    parameters: { command: { type: 'string', required: true, description: 'Bash command to execute inside the task container.' } },
    output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] },
    async execute({ command }, exec) {
      let result;
      if (transport) result = await transport.command(command, exec.signal);
      else for await (const row of requestHost('tool', {command}, exec.signal)) result = row;
      const output = result.stdout + (result.stderr ? '\n' + result.stderr : '');
      return output.slice(0, limit) + (output.length > limit ? '\n[Output clipped; use files for large results.]' : '')
        + `\n[Command finished with exit code ${result.returnCode}]`;
    },
  }));
  const connections = process.env.PHYEXP_MCP_CONNECTIONS
    ? JSON.parse(fs.readFileSync(process.env.PHYEXP_MCP_CONNECTIONS, 'utf8')) : [];
  for (const connection of connections) {
    await applyMcp(ctx, McpConfig({ serverName: connection.name, transport: connection.transport,
      url: connection.url, toolCallTimeoutMs: connection.toolCallTimeoutMs,
      failOnStartupError: true, reconnect: { enabled: false } }));
  }
  const schemas = ctx.tools.schemas();
  const receipt = {tools: schemas.map(t => t.name).sort(), schemas};
  fs.writeFileSync(process.env.PHYEXP_TOOL_RECEIPT, JSON.stringify(receipt));
  if (!transport) for await (const _ of requestHost('receipt', receipt)) {}
}
