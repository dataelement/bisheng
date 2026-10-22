import { describe, expect, it } from 'vitest';
import { normalizeHistory, selectQaPair, captureQaOperation, isCurrentQaOperation, reduceConversation, createConversation } from './index';
import { describeRun, createRunLabels, messagesForTransport, historyForHost } from './index';
const options = { mode: 'workflow' as const, sessionKey: 'panel-a', pageKey: 'first' };
it('strips internal presentation metadata from host transport payloads', () => {
  const raw = { id: 7, category: 'answer', message: 'Answer', liked: 1 };
  const host = historyForHost([raw], options);
  const transported = messagesForTransport(host);
  expect(transported[0]).toMatchObject(raw);
  expect(JSON.stringify(transported)).not.toContain('__bisheng_chat_snapshot');
  expect(transported[0]).not.toHaveProperty('chat_ui_key');
  expect(transported[0]).not.toHaveProperty('chat_source_message_id');
});
it('resolves authorized run names and distinguishes unavailable catalogs from absent metadata', () => {
  const labels = createRunLabels(key => key);
  const run = normalizeHistory([{ category: 'tool', message: { tool_key: 'search' } }], options)[0];
  expect(describeRun(run, { tool_list: [{ tool_key: 'search', name: 'Search' }] }, labels)).toEqual({ title: `${labels.used} Search`, unavailable: false });
  expect(describeRun(run, undefined, labels).unavailable).toBe(false);
  expect(describeRun(run, { tool_list: [{ tool_key: 'other' }] }, labels).unavailable).toBe(true);
});
describe('raw workflow and assistant history', () => {
  it('interprets raw rows once without dropping tool, file or reasoning rows', () => {
    const messages = normalizeHistory([
      { id: 1, category: 'question', is_bot: false, message: '{"input":"Question"}', files: '[{"name":"image.png","path":"/image"}]' },
      { id: 2, category: 'tool', is_bot: true, message: '{"name":"search","result":"found"}' },
      { id: 3, category: 'answer', is_bot: true, message: '{"content":"Answer","reasoning_content":"Reasoning"}' },
    ], options);
    expect(messages).toHaveLength(3);
    expect(messages[0]).toMatchObject({ kind: 'user', text: 'Question', sourceMessageId: '1', files: [{ name: 'image.png', url: '/image' }] });
    expect(messages[1]).toMatchObject({ kind: 'run', category: 'tool' });
    expect(messages[2]).toMatchObject({ kind: 'answer', text: 'Answer', reasoning: 'Reasoning' });
  });
  it('preserves explicit bot roles and false/zero form values', () => {
    const messages = normalizeHistory([{ id: 0, category: 'answer', is_bot: true, message: 'A' }, { category: 'input', message: { count: 0, confirmed: false } }], options);
    expect(messages[0]).toMatchObject({ kind: 'answer', sourceMessageId: '0' });
    expect(messages[1].text).toContain('0'); expect(messages[1].text).toContain('false');
  });
  it('keeps malformed payloads visible and creates page-scoped UI keys only', () => {
    const a = normalizeHistory([{ category: 'answer', message: '{bad', files: '{bad' }], options)[0];
    const b = normalizeHistory([{ category: 'answer', message: 'B' }], { ...options, pageKey: 'older' })[0];
    expect(a.text).toBe('{bad'); expect(a.sourceMessageId).toBeUndefined();
    expect(a.issues).toEqual(expect.arrayContaining(['invalid-files'])); expect(a.key).not.toBe(b.key);
  });
});
describe('QA identity and pairing', () => {
  it('pairs each chosen answer across interleaved tool rows', () => {
    const messages = normalizeHistory([{ id: 1, category: 'question', message: 'First' }, { id: 2, category: 'tool', message: 'Run' }, { id: 3, category: 'answer', message: 'A' }, { id: 4, category: 'answer', message: 'B' }, { id: 5, category: 'question', message: 'Second' }, { id: 6, category: 'answer', message: 'C' }], options);
    expect(selectQaPair(messages, messages[3].key)).toMatchObject({ question: 'First', answer: 'B', sourceMessageId: '4', questionMessageId: '1' });
    expect(selectQaPair(messages, messages[5].key)).toMatchObject({ question: 'Second', answer: 'C' });
    expect(selectQaPair(messages, messages[1].key)).toBeNull();
  });
  it('prefers valid explicit links and never manufactures server identities', () => {
    const messages = normalizeHistory([{ id: 1, category: 'question', message: 'One' }, { id: 2, category: 'question', message: 'Two' }, { id: 3, parent_message_id: 1, category: 'answer', message: 'A' }, { category: 'answer', message: 'Unknown' }], options);
    expect(selectQaPair(messages, messages[2].key)?.question).toBe('One');
    expect(selectQaPair(messages, messages[3].key)?.sourceMessageId).toBeUndefined();
  });
  it('binds completion to origin session, message, action and generation', () => {
    const origin = { taskId: 'task-1', conversationId: 'a', sourceMessageId: '3', actionId: 'save-1', sessionGeneration: 1 };
    const operation = captureQaOperation(origin); origin.conversationId = 'b';
    expect(operation.conversationId).toBe('a'); expect(isCurrentQaOperation(operation, { ...operation })).toBe(true);
    expect(isCurrentQaOperation(operation, { ...operation, conversationId: 'b' })).toBe(false);
    expect(isCurrentQaOperation(operation, { ...operation, sessionGeneration: 2 })).toBe(false);
    expect(isCurrentQaOperation(operation, { ...operation, actionId: 'save-2' })).toBe(false);
  });
});
describe('immutable per-session event reduction', () => {
  it('reconciles final identity with a stable key and explicit delta/snapshot semantics', () => {
    const initial = createConversation('a');
    const started = reduceConversation(initial, { type: 'message', sessionKey: 'a', key: 'pending-1', category: 'answer', text: 'Hel', operation: 'replace', final: false });
    const delta = reduceConversation(started, { type: 'message', sessionKey: 'a', key: 'pending-1', category: 'answer', text: 'lo', operation: 'append', final: false });
    const done = reduceConversation(delta, { type: 'message', sessionKey: 'a', key: 'pending-1', sourceMessageId: '55', category: 'answer', text: 'Hello', operation: 'replace', final: true });
    expect(done.messages).toHaveLength(1); expect(done.messages[0]).toMatchObject({ key: 'pending-1', text: 'Hello', sourceMessageId: '55', final: true });
    expect(initial.messages).toHaveLength(0); expect(started.messages[0].text).toBe('Hel');
    expect(reduceConversation(done, { type: 'message', sessionKey: 'b', key: 'wrong', category: 'answer', text: 'Other', operation: 'replace', final: true })).toBe(done);
  });
});

it('adapts normalized history to existing host state without parsing the same rows twice', async () => {
  const { historyForHost } = await import('./index');
  const messages = historyForHost([{ id: 4, is_bot: true, category: 'answer', message: '{"msg":"Hello"}', files: '[{"name":"report.pdf","path":"/report"}]' }], options);
  expect(messages[0]).toMatchObject({ id: 4, category: 'answer', message: { msg: 'Hello' }, isSend: false, end: true, chatKey: 'msg', files: [{ file_name: 'report.pdf', file_url: '/report' }] });
});


describe('workflow wire protocol', () => {
  it('treats tokens as deltas even when a token repeats the whole previous text', async () => {
    const { applyWorkflowStream } = await import('./index');
    const started = applyWorkflowStream([], { type: 'stream', category: 'stream_msg', message: { unique_id: 'n1', output_key: 'a', msg: 'ha', reasoning_content: 'r' } }, 's');
    const next = applyWorkflowStream(started, { type: 'stream', category: 'stream_msg', message: { unique_id: 'n1', output_key: 'a', msg: 'ha' } }, 's');
    expect(next[0]).toMatchObject({ text: 'haha', reasoning: 'r', final: false });
    expect(started[0].text).toBe('ha');
    const done = applyWorkflowStream(next, { type: 'end', category: 'stream_msg', message_id: 45, citations: [{ citationId: 'c' }], files: [{ file_name: 'a', file_url: '/a' }], message: { unique_id: 'n1', output_key: 'a', msg: 'Final', reasoning_content: 'reason' } }, 's');
    expect(done[0]).toMatchObject({ key: started[0].key, text: 'Final', reasoning: 'reason', sourceMessageId: '45', final: true, files: [{ name: 'a', url: '/a' }], raw: { citations: [{ citationId: 'c' }] } });
  });
  it('separates outputs of one node and accepts an end with no preceding start', async () => {
    const { applyWorkflowStream } = await import('./index');
    const rows = applyWorkflowStream([], { type: 'end', category: 'stream_msg', message_id: 5, message: { unique_id: 'n', output_key: 'one', msg: 'A' } }, 's');
    const next = applyWorkflowStream(rows, { type: 'stream', category: 'stream_msg', message: { unique_id: 'n', output_key: 'two', msg: 'B' } }, 's');
    expect(next.map(row => row.text)).toEqual(['A', 'B']);
    expect(next[0].final).toBe(true);
    expect(next[1].sourceMessageId).toBeUndefined();
  });
});


it('reuses canonical history payloads and refreshes only host metadata for presentation', async () => {
  const { historyForHost, messagesForPresentation } = await import('./index');
  const rows = historyForHost([{ id: 7, category: 'answer', message: '{"msg":"Answer"}', files: '[]', liked: 0 }], options);
  const first = messagesForPresentation(rows, options)[0];
  const liked = messagesForPresentation([{ ...rows[0], liked: 1 }], options)[0];
  expect(liked.payload).toBe(first.payload);
  expect(liked.text).toBe('Answer'); expect(liked.raw.liked).toBe(1);
  const edited = messagesForPresentation([{ ...rows[0], message: 'Changed' }], options)[0];
  expect(edited.text).toBe('Changed');
});


it('retains private protocol rows without presenting them as customer messages', () => {
  const rows = normalizeHistory([
    { id: 1, category: 'question', is_bot: 1, message: 'Q' },
    { id: 2, category: 'tool_call', is_bot: true, message: '{"tool_calls":[]}' },
    { id: 3, category: 'tool_result', is_bot: true, message: '{"content":"internal"}' },
    { id: 4, category: 'input', message: '{"input_schema":{"value":[]}}' },
    { id: 5, category: 'answer', is_bot: 1, message: 'A' },
  ], options);
  expect(rows).toHaveLength(5);
  expect(rows.map(row => row.kind)).toEqual(['user', 'hidden', 'hidden', 'hidden', 'answer']);
  expect(selectQaPair(rows, rows[4].key)).toMatchObject({ question: 'Q', answer: 'A' });
});


it('keeps reasoning outside the QA action model and displays host system notes as system text', () => {
  const rows = normalizeHistory([{ id: 1, category: 'question', message: 'Q' },
    { id: 2, category: 'reasoning_answer', message: 'Reasoning' },
    { id: 3, category: 'answer', message: 'A' },
    { category: 'guide', is_bot: false, message: '', thought: 'Configuration updated' }], options);
  expect(rows[1].kind).toBe('reasoning');
  expect(selectQaPair(rows, rows[1].key)).toBeNull();
  expect(selectQaPair(rows, rows[2].key)?.answer).toBe('A');
  expect(rows[3]).toMatchObject({ kind: 'system', text: 'Configuration updated' });
});
