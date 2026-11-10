import request from './request';
import { TextDecoder } from 'util';
import { fetchProjectConversations, fetchProjectSnapshot, ProjectApiError, streamProjectEvents, unwrapProjectEnvelope } from './chatProjects';

jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));
const page = (revision: string, projects: unknown[] = [], next_cursor: string | null = null) => ({
  status_code: 200, data: { protocol_version: 1, identity: { user_id: 7, tenant_id: 1 }, revision, projects, memberships: [], next_cursor },
});
const first = '11111111-1111-4111-8111-111111111111';
const second = '22222222-2222-4222-8222-222222222222';

const conversation = {
  conversationId: 'chat-one', user: '7', title: 'Project conversation', model: null,
  createdAt: '2026-11-06T10:00:00', updateAt: '2026-11-06T11:00:00',
  chat_id: 'chat-one', name: 'Project conversation', flow_id: '', flow_type: 15,
  flow_name: null, create_time: '2026-11-06T10:00:00', update_time: '2026-11-06T11:00:00',
};
const conversationPage = (rows: unknown[]) => ({
  status_code: 200, data: { data: rows, total: rows.length, revision: '3', next_cursor: null },
});

it.each([15, 20, 10])('loads nonempty project conversation data for flow type %s', async flowType => {
  jest.mocked(request.get).mockResolvedValueOnce(conversationPage([{ ...conversation, flow_type: flowType }]));

  const result = await fetchProjectConversations({ project_id: first });

  expect(result).toEqual({
    data: [expect.objectContaining({
      conversationId: conversation.chat_id, title: conversation.name, user: '7',
      createdAt: conversation.create_time, updatedAt: conversation.update_time,
      endpoint: null, model: null, flowId: '', flowType,
    })],
    total: 1, revision: '3', next_cursor: null,
  });
});

it('loads project conversation search results through the same validated adapter', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(conversationPage([conversation]));
  const signal = new AbortController().signal;

  const result = await fetchProjectConversations({ query: 'Project', cursor: 'next' }, signal);

  expect(result.data[0]).toMatchObject({ conversationId: 'chat-one', endpoint: null });
  expect(request.get).toHaveBeenLastCalledWith('api/v1/chat/projects/conversations', expect.objectContaining({
    signal, params: { query: 'Project', cursor: 'next' },
  }));
});

it('keeps an empty project conversation page as an empty success', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(conversationPage([]));
  expect(await fetchProjectConversations({ project_id: first })).toEqual({ data: [], total: 0, revision: '3', next_cursor: null });
});

it('rejects invalid conversation fields with a project error instead of exposing validation details', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(conversationPage([{ ...conversation, createdAt: null }]));
  await expect(fetchProjectConversations({ project_id: first })).rejects.toThrow(ProjectApiError);
});

it('assembles all pages before exposing the snapshot', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(page('2', [{ id: first, name: 'One' }], 'next')).mockResolvedValueOnce(page('2', [{ id: second, name: 'Two' }]));
  const result = await fetchProjectSnapshot(new AbortController().signal);
  expect(result.projects.map(p => p.id)).toEqual([first, second]);
  expect(result.next_cursor).toBeNull();
});

it('restarts a snapshot invalidated while its pages were loading', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(page('2', [], 'old')).mockResolvedValueOnce({ status_code: 13013 }).mockResolvedValueOnce(page('3', [{ id: first, name: 'Latest' }]));
  expect((await fetchProjectSnapshot(new AbortController().signal)).revision).toBe('3');
});

it('rejects malformed, unsupported and failed envelopes instead of showing an empty success', () => {
  expect(() => unwrapProjectEnvelope('<html>Login</html>')).toThrow(ProjectApiError);
  expect(() => unwrapProjectEnvelope({ status_code: 13011 })).toThrow(ProjectApiError);
});

it('does not publish a page below the observed event version', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(page('2')).mockResolvedValueOnce(page('3'));
  expect((await fetchProjectSnapshot(new AbortController().signal, () => '3')).revision).toBe('3');
});

it('rejects duplicate identities and dangling memberships after assembling the snapshot', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(page('2', [{ id: first, name: 'One' }, { id: first, name: 'Again' }]));
  await expect(fetchProjectSnapshot(new AbortController().signal)).rejects.toThrow(ProjectApiError);
  const invalid = page('2');
  jest.mocked(request.get).mockResolvedValueOnce({ ...invalid, data: { ...invalid.data, memberships: [{ chat_id: 'chat-one', project_id: first }] } });
  await expect(fetchProjectSnapshot(new AbortController().signal)).rejects.toThrow(ProjectApiError);
});

it('parses SSE across CRLF chunk boundaries and releases its reader when the connection ends', async () => {
  const previous = { fetch: globalThis.fetch, TextDecoder: globalThis.TextDecoder };
  const chunks = ['event: changed\r', '\ndata: {"protocol_version":1,"revision":"4"}\r\n\r', '\n'];
  const reader = { read: jest.fn(async () => chunks.length ? { done: false, value: Buffer.from(chunks.shift() ?? '') } : { done: true }), cancel: jest.fn(), releaseLock: jest.fn() };
  Object.assign(globalThis, { TextDecoder, fetch: jest.fn(async () => ({ ok: true, headers: { get: () => 'text/event-stream' }, body: { getReader: () => reader } })) });
  const receive = jest.fn();
  try {
    await expect(streamProjectEvents(new AbortController().signal, receive)).rejects.toThrow(ProjectApiError);
    expect(receive).toHaveBeenCalledWith('changed', { protocol_version: 1, revision: '4' });
    expect(reader.cancel).toHaveBeenCalledTimes(1);
    expect(reader.releaseLock).toHaveBeenCalledTimes(1);
  } finally { Object.assign(globalThis, previous); }
});
