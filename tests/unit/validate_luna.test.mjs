import test from 'node:test';
import assert from 'node:assert/strict';
import { validateLuna } from '../smoke/luna/validate.mjs';

const expected = { nonce: 'random-file-nonce', sum: 42 };
const exit = { code: 0, signal: null };
const source = { provider: 'openai-codex', model: 'gpt-6-luna' };
function fixture() {
  return structuredClone([
    { type: 'request/header', data: { header: { config: { ...source, reasoningEffort: 'medium' } } } },
    { type: 'assistant/message', data: { message: { source, content: [{ type: 'tool-call', name: 'bash' }] } } },
    { type: 'tool/call', data: { name: 'bash', callId: 'call-1' } },
    { type: 'tool/result', data: { message: { toolCallId: 'call-1', isError: false,
      content: [{ type: 'text', text: 'random-file-nonce' }] } } },
    { type: 'assistant/message', data: { message: { source,
      content: [{ type: 'text', text: JSON.stringify(expected) }] } } },
    { type: 'turn/end', data: { reason: { kind: 'completed' } } },
  ]);
}
test('accepts a correlated tool round trip with an exact answer and clean shutdown', () => {
  assert.equal(validateLuna(fixture(), expected, exit).checks.answerCorrect, true);
});
test('rejects a plausible answer without executing a tool', () => {
  assert.throws(() => validateLuna(fixture().filter(e => !e.type.startsWith('tool/')), expected, exit));
});
test('rejects a tool error or unrelated result', () => {
  for (const change of [{ isError: true }, { toolCallId: 'different-call' }]) {
    const events = fixture();
    Object.assign(events[3].data.message, change);
    assert.throws(() => validateLuna(events, expected, exit));
  }
});
test('rejects model substitution', () => {
  const events = fixture();
  events[4].data.message.source.model = 'another-model';
  assert.throws(() => validateLuna(events, expected, exit));
});
test('rejects incorrect arithmetic and aborted turns', () => {
  assert.throws(() => validateLuna(fixture(), { ...expected, sum: 43 }, exit));
  const events = fixture();
  events[5].data.reason.kind = 'aborted';
  assert.throws(() => validateLuna(events, expected, exit));
});
test('rejects abnormal process termination', () => {
  assert.throws(() => validateLuna(fixture(), expected, { code: null, signal: 'SIGTERM' }));
});
