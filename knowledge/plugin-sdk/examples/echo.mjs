// Technical API example; not an experiment strategy. Config is supplied by the recipe.
import { defineTool } from '@deepseek-ai/dsh-tools';
export const name = 'example-echo';
export const inject = ['tools', 'systemPrompt'];
export function apply(ctx, config = {}) {
  ctx.systemPrompt.context({ name: 'example-context', order: 9000, text: 'Example fixture: echo is available.' });
  ctx.tools.register(defineTool({
    name: 'example_echo', description: 'Return a supplied string.',
    parameters: { text: { type: 'string', required: true } },
    output: { schema: { type: 'string' }, render: (_, text) => [{ type: 'text', text }] },
    async execute({ text }) { return text; },
  }));
  ctx.on('tools/post-execute', async (exec, result, next) => {
    if (exec.name === 'example_echo' && !result.isError && config.prefix)
      return { kind: 'accept', value: config.prefix + result.value };
    return next();
  });
}
