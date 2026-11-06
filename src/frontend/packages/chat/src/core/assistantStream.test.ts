import { expect, it } from 'vitest';
import { assistantStreamForHost, startAssistantForHost } from './assistantStream';
it('keeps repeated delta tokens and reconciles the final cover with a persisted ID', () => {
  const started = startAssistantForHost([], { type: 'start', category: 'processing' }, 'a');
  const first = assistantStreamForHost(started, { type: 'stream', message: { content: 'ha', reasoning_content: 'r' } }, 'a');
  const second = assistantStreamForHost(first, { type: 'stream', message: 'ha' }, 'a');
  expect(second[0].message).toBe('haha'); expect(started[0].message).toBe('');
  const finalStart = startAssistantForHost(second, { type: 'start', category: 'answer' }, 'a');
  const done = assistantStreamForHost(finalStart, { type: 'end_cover', category: 'answer', message_id: 55, message: 'Final', citations: [{ citationId: 'c' }] }, 'a');
  expect(done).toHaveLength(1);
  expect(done[0]).toMatchObject({ message: 'Final', reasoning_log: 'r', id: 55, chat_ui_key: started[0].chat_ui_key, chat_source_message_id: '55', end: true, citations: [{ citationId: 'c' }] });
});
it('updates the matching nested run without overwriting another run or question', () => {
  const initial = [{ category: 'question', isSend: true, message: 'Q', id: 1 }];
  const a = startAssistantForHost(initial, { type: 'start', category: 'tool', extra: 'a', message: '{"tool_key":"a"}' }, 's');
  const b = startAssistantForHost(a, { type: 'start', category: 'tool', extra: 'b', message: '{"tool_key":"b"}' }, 's');
  const done = assistantStreamForHost(b, { type: 'end', category: 'tool', extra: 'a', message: '{"tool_key":"a","output":"A"}' }, 's');
  expect(done[0]).toBe(initial[0]);
  expect(done[1]).toMatchObject({ end: true, message: { output: 'A' } });
  expect(done[2]).toMatchObject({ end: false, message: { tool_key: 'b' } });
});
it('accepts a final answer without a preceding start and does not assign a fake persisted ID', () => {
  const done = assistantStreamForHost([], { type: 'end', category: 'answer', message: 'A' }, 's');
  expect(done[0]).toMatchObject({ end: true, message: 'A', chat_source_message_id: undefined });
});
it('closes only the current turn on the host runtime-error control frame without adding an empty tool', () => {
  const previousTurn = [{ id: 1, category: 'answer', message: 'Earlier', end: true }, { id: 2, category: 'question', isSend: true, message: 'Q' }];
  const tool = startAssistantForHost(previousTurn, { type: 'start', category: 'tool', extra: 'search', message: '{"tool_key":"search"}' }, 's');
  const answer = startAssistantForHost(tool, { type: 'start', category: 'processing' }, 's');
  const closed = assistantStreamForHost(answer, { type: 'end_cover', category: 'tool', message: '{}' }, 's', true);
  expect(closed).toHaveLength(answer.length);
  expect(closed.slice(2).every(row => row.end === true)).toBe(true);
  expect(closed[0]).toBe(previousTurn[0]);
  expect(closed[2].message).toEqual({ tool_key: 'search' });
});
