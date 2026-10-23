import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeUsage } from '../../src/runtime/core/usage.mjs';
import {summarizeWireUsage} from '../../src/execution/host/usage.mjs';

test('pi-ai cached tokens contribute to prompt totals, without double-counting output', () => {
  const events = [{ inputTokens: 100, outputTokens: 5, totalTokens: 105 },
    { inputTokens: 20, cacheReadTokens: 90, outputTokens: 10, totalTokens: 120 }]
    .map(usage => ({ type: 'assistant/message', data: { usage } }));
  const result = summarizeUsage(events);
  assert.equal(result.inputTokens, 120);
  assert.equal(result.cacheReadTokens, 90);
  assert.equal(result.promptTokens, 210);
  assert.equal(result.totalTokens, 225);
});

test('missing authoritative totals remain unknown', () => {
  const result = summarizeUsage([{ type: 'assistant/message', data: { usage: { inputTokens: 2, outputTokens: 1 } } }]);
  assert.equal(result.totalTokens, null);
  assert.equal(result.promptTokens, null);
});
test('external CLI usage comes from every gateway receipt including auxiliary requests',()=>{
 const audit=[{type:'admitted'},{type:'settled',usage:{inputTokens:7,cacheReadTokens:3,outputTokens:2,totalTokens:12}},
  {type:'settled',usage:{inputTokens:0,outputTokens:0,totalTokens:0}}];
 assert.deepEqual({...summarizeWireUsage(audit),accounting:undefined},{inputTokens:7,outputTokens:2,totalTokens:12,cacheReadTokens:3,cacheWriteTokens:0,promptTokens:10,accounting:undefined});
 assert.equal(summarizeWireUsage([...audit,{type:'settled',usage:null}]).totalTokens,null);
});
