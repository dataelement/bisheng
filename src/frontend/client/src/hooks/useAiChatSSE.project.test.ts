import type { ChatMessage } from '~/api/chatApi';
import { openChatStream, type SSESubmission } from './useAiChatSSE';
import { captureProjectChatDraft } from '~/layouts/WorkbenchSidebar/projectChatCreation';

type Listener = (event: { data: string }) => void;
const mockStreams: Array<{ listeners: Record<string, Listener>; payload: Record<string, unknown> }> = [];
jest.mock('sse.js', () => ({ SSE: jest.fn().mockImplementation((_url, options) => {
  const listeners: Record<string, Listener> = {};
  mockStreams.push({ listeners, payload: JSON.parse(options.payload) });
  return { addEventListener: (name: string, listener: Listener) => { listeners[name] = listener; }, stream: jest.fn(), close: jest.fn() };
}) }));
jest.mock('~/api/chatApi', () => ({ getSSEUrl: () => '/api/chat' }));
jest.mock('~/api/request', () => ({ translateApiErrorMessage: () => '' }));

const projectId = '11111111-1111-4111-8111-111111111111';
function start(overrides: Partial<SSESubmission> = {}) {
  const submission: SSESubmission = {
    payload: { conversationId: null, text: 'Hello' }, userMessage: { conversationId: '' } as ChatMessage,
    onCreated: jest.fn(), onMessage: jest.fn(), onFinal: jest.fn(),
    onStart: jest.fn(), onError: jest.fn(), onEnd: jest.fn(), onTaskHandoff: jest.fn(), ...overrides,
  };
  openChatStream(submission, key => key);
  const stream = mockStreams[mockStreams.length - 1];
  return { submission, payload: stream.payload, emit: (data: unknown, event = 'message') => stream.listeners[event]({ data: JSON.stringify(data) }) };
}
beforeEach(() => {
  sessionStorage.clear(); localStorage.clear(); mockStreams.length = 0;
  window.history.replaceState({ key: 'project-draft' }, '', '/workspace/c/new?projectId=' + projectId);
});

it('submits immutable project intent before created and never writes a local assignment', () => {
  const stream = start();
  expect(stream.payload).toMatchObject({ project_id: projectId, project_request_id: expect.any(String) });
  window.history.replaceState({}, '', '/workspace/c/new');
  stream.emit({ created: true, message: { conversationId: 'created-chat', messageId: '42' } });
  expect(localStorage.getItem('bs_mock_project_chats')).toBeNull();
  expect(stream.submission.onCreated).toHaveBeenCalledWith('created-chat', expect.objectContaining({ messageId: '42' }));
});

it('sends the same project intent for task-mode handoff', () => {
  const stream = start({ payload: { conversationId: null, task_mode: true } });
  stream.emit({ event: 'linsight_task_handoff', data: { chat_id: 'task-chat', session_version_id: 'sv' } });
  expect(stream.payload.project_id).toBe(projectId);
  expect(stream.submission.onTaskHandoff).toHaveBeenCalledWith({ chat_id: 'task-chat', session_version_id: 'sv' });
  expect(localStorage.getItem('bs_mock_project_chats')).toBeNull();
});

it('accepts an explicitly supplied ordinary workstation endpoint', () => {
  expect(start({ sseUrl: '/workspace/api/v1/workstation/chat/completions' }).payload.project_id).toBe(projectId);
});

it.each([
  ['/workspace/c/new', null, undefined],
  ['/workspace/c/existing?projectId=PROJECT', 'existing', undefined],
  ['/workspace/channel?projectId=PROJECT', null, undefined],
  ['/workspace/c/new?projectId=PROJECT', null, '/subscription/chat'],
])('does not submit intent for an unrelated stream from %s', (path, conversationId, sseUrl) => {
  window.history.replaceState({}, '', path.replace('PROJECT', projectId));
  expect(start({ payload: { conversationId }, sseUrl }).payload.project_id).toBeUndefined();
});

it('restores an existing conversation on a replay instead of starting another generation', () => {
  const recovered = jest.fn();
  window.addEventListener('bisheng:project-conversation-recovered', recovered);
  const stream = start();
  stream.emit({ status_code: 13018, data: { chat_id: 'existing-chat' } }, 'error');
  expect(recovered).toHaveBeenCalledTimes(1);
  expect(stream.submission.onError).not.toHaveBeenCalled();
  expect(stream.submission.onEnd).toHaveBeenCalledTimes(1);
  window.removeEventListener('bisheng:project-conversation-recovered', recovered);
});

it('does not navigate a later draft when an earlier project request is replayed', () => {
  const projectDraft = captureProjectChatDraft(null);
  const recovered = jest.fn();
  window.addEventListener('bisheng:project-conversation-recovered', recovered);
  window.history.replaceState({}, '', '/workspace/c/new?projectId=22222222-2222-4222-8222-222222222222');
  const stream = start({ projectDraft });
  expect(stream.payload.project_id).toBe(projectId);
  stream.emit({ status_code: 13018, data: { chat_id: 'existing-chat' } }, 'error');
  expect(recovered).not.toHaveBeenCalled();
  expect(stream.submission.onEnd).toHaveBeenCalledTimes(1);
  window.removeEventListener('bisheng:project-conversation-recovered', recovered);
});

it('does not recover an old chat into a different logical draft with the same project URL', () => {
  window.history.replaceState({ key: 'first-router-key', usr: { newChatKey: 'first-intent' } }, '', window.location.href);
  const projectDraft = captureProjectChatDraft(null);
  const recovered = jest.fn();
  window.addEventListener('bisheng:project-conversation-recovered', recovered);
  window.history.replaceState({ key: 'second-router-key', usr: { newChatKey: 'second-intent' } }, '', window.location.href);
  const stream = start({ projectDraft });
  stream.emit({ status_code: 13018, data: { chat_id: 'old-chat' } }, 'error');
  expect(recovered).not.toHaveBeenCalled();
  expect(stream.submission.onEnd).toHaveBeenCalledTimes(1);
  window.removeEventListener('bisheng:project-conversation-recovered', recovered);
});
