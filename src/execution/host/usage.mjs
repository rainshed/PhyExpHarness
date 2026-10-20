// Native DeepSeek and pi-ai adapters report uncached input; zero cache counters may be omitted.
// Keep provider total authoritative and expose aggregate prompt tokens for Harbor.
export function summarizeUsage(events) {
  const samples = events.filter(e => e.type === 'assistant/message').map(e => e.data.usage);
  const sum = key => samples.every(u => Number.isFinite(u?.[key]))
    ? samples.reduce((total, u) => total + u[key], 0) : null;
  const usage = { inputTokens: sum('inputTokens'), outputTokens: sum('outputTokens'), totalTokens: sum('totalTokens'),
    cacheReadTokens: samples.reduce((total, u) => total + (u?.cacheReadTokens || 0), 0),
    cacheWriteTokens: samples.reduce((total, u) => total + (u?.cacheWriteTokens || 0), 0) };
  usage.promptTokens = usage.totalTokens !== null && usage.outputTokens !== null
    ? usage.totalTokens - usage.outputTokens : null;
  usage.accounting = 'inputTokens excludes cache; promptTokens includes cache; totalTokens includes prompt and output';
  return usage;
}
