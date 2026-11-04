import type { ChatMessage } from '~/api/chatApi';
import { createMockProject, deleteMockProject, moveChatToProject } from '~/layouts/WorkbenchSidebar/projectsStore';
import { openChatStream, type SSESubmission } from './useAiChatSSE';

type Listener = (event: { data: string }) => void;
const mockStreams: Array<Record<string, Listener>> = [];
jest.mock('sse.js', () => ({ SSE: jest.fn().mockImplementation(() => {
  const listeners: Record<string, Listener> = {};
  mockStreams.push(listeners);
  return { addEventListener: (name: string, listener: Listener) => { listeners[name] = listener; }, stream: jest.fn(), close: jest.fn() };
}) }));
jest.mock('~/api/chatApi', () => ({ getSSEUrl: () => '/api/chat' }));
jest.mock('~/api/request', () => ({ translateApiErrorMessage: () => '' }));

function start(overrides: Partial<SSESubmission> = {}) {
  const submission: SSESubmission = {
    payload: { conversationId: null }, userMessage: { conversationId: '' } as ChatMessage,
    onCreated: jest.fn(), onMessage: jest.fn(), onFinal: jest.fn(),
    onStart: jest.fn(), onError: jest.fn(), onEnd: jest.fn(), onTaskHandoff: jest.fn(),
    ...overrides,
  };
  openChatStream(submission, key => key);
  const listeners = mockStreams[mockStreams.length - 1];
  return { submission, emit: (data: unknown) => listeners.message({ data: JSON.stringify(data) }) };
}

const assignments = () => JSON.parse(localStorage.getItem('bs_mock_project_chats') ?? '{}');
let projectId: string;

beforeEach(() => {
  projectId = createMockProject('e2e-project-chat').id;
  window.history.replaceState({}, '', `/workspace/c/new?projectId=${projectId}`);
});
afterEach(() => deleteMockProject(projectId));

it('files the server-created conversation under the project captured before navigation', () => {
  const stream = start();
  window.history.replaceState({}, '', '/workspace/c/new?projectId=another-project');
  stream.emit({ created: true, message: { conversationId: 'created-chat', messageId: '42' } });
  expect(assignments()['created-chat']).toBe(projectId);
  expect(assignments().new).toBeUndefined();
  expect(stream.submission.onCreated).toHaveBeenCalledWith('created-chat', expect.objectContaining({ messageId: '42' }));
  // A duplicate event cannot undo a later explicit move by the user.
  moveChatToProject('created-chat', 'another-project');
  stream.emit({ created: true, message: { conversationId: 'created-chat' } });
  expect(assignments()['created-chat']).toBe('another-project');
});

it('files task-mode handoffs under the selected project', () => {
  const stream = start();
  stream.emit({ event: 'linsight_task_handoff', data: { chat_id: 'task-chat', session_version_id: 'sv' } });
  expect(assignments()['task-chat']).toBe(projectId);
  expect(stream.submission.onTaskHandoff).toHaveBeenCalledWith({ chat_id: 'task-chat', session_version_id: 'sv' });
});

it('leaves no assignment when the project is deleted before the creation event', () => {
  const stream = start();
  deleteMockProject(projectId);
  stream.emit({ created: true, message: { conversationId: 'orphan-chat' } });
  expect(assignments()['orphan-chat']).toBeUndefined();
});

it.each([
  ['/workspace/c/new', null, undefined],
  ['/workspace/c/existing?projectId=PROJECT', 'existing', undefined],
  ['/workspace/channel?projectId=PROJECT', null, undefined],
  ['/workspace/c/new?projectId=missing', null, undefined],
  ['/workspace/c/new?projectId=PROJECT', null, '/subscription/chat'],
])('does not file an unrelated conversation from %s', (path, conversationId, sseUrl) => {
  window.history.replaceState({}, '', path.replace('PROJECT', projectId));
  const stream = start({ payload: { conversationId }, sseUrl });
  stream.emit({ created: true, message: { conversationId: 'unrelated-chat' } });
  expect(assignments()['unrelated-chat']).toBeUndefined();
});

it('does not create a placeholder assignment before a successful creation', () => {
  const stream = start();
  stream.emit({ created: true, message: { conversationId: 'new' } });
  stream.emit({ final: true });
  expect(Object.values(assignments())).not.toContain(projectId);
});
