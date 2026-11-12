import request from './request';
import { fetchProjectConversations, fetchProjectSnapshot, performProjectAction, ProjectApiError, unwrapProjectEnvelope } from './chatProjects';

jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));
const page = (projects: unknown[] = [], memberships: unknown[] = []) => ({
  status_code: 200, data: { identity: { user_id: 7, tenant_id: 1 }, projects, memberships },
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
  status_code: 200, data: { data: rows, total: rows.length, next_cursor: null },
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
    total: 1, next_cursor: null,
  });
});

it('loads project conversation search results through the same validated adapter', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(conversationPage([conversation]));
  const signal = new AbortController().signal;

  const result = await fetchProjectConversations({ query: 'Project', cursor: '40' }, signal);

  expect(result.data[0]).toMatchObject({ conversationId: 'chat-one', endpoint: null });
  expect(request.get).toHaveBeenLastCalledWith('api/v1/chat/projects/conversations', expect.objectContaining({
    signal, params: { query: 'Project', cursor: '40' },
  }));
});

it('keeps an empty project conversation page as an empty success', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(conversationPage([]));
  expect(await fetchProjectConversations({ project_id: first })).toEqual({ data: [], total: 0, next_cursor: null });
});

it('rejects invalid conversation fields with a project error instead of exposing validation details', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(conversationPage([{ ...conversation, createdAt: null }]));
  await expect(fetchProjectConversations({ project_id: first })).rejects.toThrow(ProjectApiError);
});

it('loads the whole snapshot in one request', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(page([{ id: first, name: 'One' }, { id: second, name: 'Two' }], [{ chat_id: 'chat-one', project_id: first }]));
  const result = await fetchProjectSnapshot(new AbortController().signal);
  expect(result.projects.map(p => p.id)).toEqual([first, second]);
  expect(result.memberships).toEqual([{ chat_id: 'chat-one', project_id: first }]);
});

it('rejects malformed, unsupported and failed envelopes instead of showing an empty success', () => {
  expect(() => unwrapProjectEnvelope('<html>Login</html>')).toThrow(ProjectApiError);
  expect(() => unwrapProjectEnvelope({ status_code: 13011 })).toThrow(ProjectApiError);
});

it('rejects dangling memberships', async () => {
  jest.mocked(request.get).mockResolvedValueOnce(page([], [{ chat_id: 'chat-one', project_id: first }]));
  await expect(fetchProjectSnapshot(new AbortController().signal)).rejects.toThrow(ProjectApiError);
});

it('sends a create with its client-generated project id and no request id', async () => {
  jest.mocked(request.post).mockResolvedValueOnce({ status_code: 200, data: { outcome: { project_id: first } } });
  const result = await performProjectAction({ operation: 'create', project_id: first, name: 'One' });
  expect(result.outcome.project_id).toBe(first);
  expect(request.post).toHaveBeenLastCalledWith('api/v1/chat/projects/actions', { operation: 'create', project_id: first, name: 'One' }, expect.anything());
});
