import assert from 'node:assert/strict';

// A plausible final answer alone must never pass this integration check.
export function validateLuna(events, expected, exit) {
  const model = 'gpt-6-luna';
  const provider = 'openai-codex';
  const headers = events.filter(e => e.type === 'request/header').map(e => e.data.header);
  assert.ok(headers.length >= 1, 'Missing model request configuration');
  for (const header of headers) {
    assert.equal(header.config.model, model, 'Unexpected model');
    assert.equal(header.config.provider, provider, 'Unexpected provider');
    assert.equal(header.config.reasoningEffort, 'medium', 'Unexpected reasoning effort');
  }
  const assistants = events.filter(e => e.type === 'assistant/message').map(e => e.data);
  assert.ok(assistants.length >= 2, 'Expected a model response before and after the tool result');
  for (const assistant of assistants) {
    assert.equal(assistant.message.source.model, model, 'Assistant source model mismatch');
    assert.equal(assistant.message.source.provider, provider, 'Assistant source provider mismatch');
  }
  const calls = events.filter(e => e.type === 'tool/call' && e.data.name === 'bash');
  assert.ok(calls.length > 0, 'No bash tool call');
  const resultIndex = events.findIndex(e => e.type === 'tool/result'
    && calls.some(c => c.data.callId === e.data.message.toolCallId)
    && e.data.message.isError === false
    && e.data.message.content.some(c => c.type === 'text' && c.text.includes(expected.nonce)));
  assert.ok(resultIndex >= 0, 'No successful correlated tool result containing the file nonce');
  const finalIndex = events.findLastIndex(e => e.type === 'assistant/message');
  assert.ok(finalIndex > resultIndex, 'Final answer must follow the tool result');
  const final = events[finalIndex].data.message;
  assert.ok(!final.content.some(c => c.type === 'tool-call'), 'Final response still requests a tool');
  const finalText = final.content.filter(c => c.type === 'text').map(c => c.text).join('');
  assert.deepEqual(JSON.parse(finalText), expected, 'Nonce or sum is incorrect');
  assert.ok(events.some(e => e.type === 'turn/end' && e.data.reason?.kind === 'completed'),
    'Missing successful durable end-of-turn event');
  assert.deepEqual(exit, { code: 0, signal: null }, 'Runtime did not exit cleanly');
  const usage = assistants.reduce((sum, message) => {
    for (const key of ['inputTokens', 'outputTokens', 'totalTokens']) sum[key] += message.usage?.[key] || 0;
    return sum;
  }, { inputTokens: 0, outputTokens: 0, totalTokens: 0 });
  return { finalText, toolCalls: calls.length, successfulModelResponses: assistants.length, usage,
    checks: { modelAndProvider: true, toolExecuted: true, toolResultConsumed: true,
      answerCorrect: true, turnEnded: true, cleanExit: true } };
}
