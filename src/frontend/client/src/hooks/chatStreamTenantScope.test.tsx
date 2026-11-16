import { act, renderHook } from '@testing-library/react';
import { prepareBrowserHeaders } from '~/api/request';
import { openChatStream, type SSESubmission } from './useAiChatSSE';
import useStreamChatSSE, { type StreamChatSSESubmission } from './useStreamChatSSE';

// Keep the real SSE library: its default constructor sends immediately.
jest.mock('~/api/request', () => ({ prepareBrowserHeaders: jest.fn(), translateApiErrorMessage: () => '' }));
jest.mock('~/api/chatApi', () => ({ getSSEUrl: () => '/workspace/api/v1/workstation/chat/completions' }));
jest.mock('~/layouts/WorkbenchSidebar/projectChatCreation', () => ({
  captureProjectChatDraft: () => null,
  bindProjectChatCreation: () => ({}),
}));

const prepare = jest.mocked(prepareBrowserHeaders);
const requests: Array<{ headers: Record<string, string>; body: unknown }> = [];
let requestHeaders = new WeakMap<XMLHttpRequest, Record<string, string>>();
let resolveScope: (headers: Record<string, string>) => void;
let rejectScope: (error: Error) => void;
const cleanups: Array<() => void> = [];

beforeEach(() => {
  requests.length = 0;
  requestHeaders = new WeakMap();
  prepare.mockReturnValue(new Promise((resolve, reject) => { resolveScope = resolve; rejectScope = reject; }));
  jest.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
  jest.spyOn(XMLHttpRequest.prototype, 'open').mockImplementation(function (this: XMLHttpRequest) {
    requestHeaders.set(this, {});
  });
  jest.spyOn(XMLHttpRequest.prototype, 'setRequestHeader').mockImplementation(function (this: XMLHttpRequest, name, value) {
    requestHeaders.get(this)![name] = value;
  });
  jest.spyOn(XMLHttpRequest.prototype, 'send').mockImplementation(function (this: XMLHttpRequest, body) {
    requests.push({ headers: { ...requestHeaders.get(this) }, body });
  });
});

afterEach(async () => {
  cleanups.splice(0).forEach(close => close());
  await act(async () => { await Promise.resolve(); });
  jest.restoreAllMocks();
});

function start(kind: 'task' | 'stream') {
  const onError = jest.fn();
  const onEnd = jest.fn();
  if (kind === 'task') {
    const submission: SSESubmission = {
      payload: { task_mode: true, text: 'Question' }, projectDraft: null,
      userMessage: { conversationId: '', messageId: 'question', parentMessageId: '', sender: 'user', text: 'Question' },
      flowLeaseId: 'lease-1', onCreated: jest.fn(), onMessage: jest.fn(), onFinal: jest.fn(),
      onStart: jest.fn(), onError, onEnd,
    };
    const handle = openChatStream(submission, key => key);
    cleanups.push(handle.close);
    return { close: handle.close, onError, onEnd };
  }
  const submission: StreamChatSSESubmission = {
    sseUrl: '/workspace/api/v1/channel/chat', payload: { question: 'Question' },
    onStart: jest.fn(), onMessage: jest.fn(), onFinal: jest.fn(), onError, onEnd,
  };
  const hook = renderHook(() => useStreamChatSSE(submission));
  cleanups.push(hook.unmount);
  return { close: hook.unmount, onError, onEnd };
}

it.each(['task', 'stream'] as const)('%s sends only once after the tenant proof is ready', async kind => {
  start(kind);
  expect(requests).toHaveLength(0);
  await act(async () => { resolveScope({ 'X-Management-Tenant': '25' }); });
  expect(requests).toHaveLength(1);
  expect(requests[0].headers).toMatchObject({ 'Content-Type': 'application/json', 'X-Management-Tenant': '25' });
  if (kind === 'task') {
    expect(requests[0].headers['X-Flow-Lease-Id']).toBe('lease-1');
    expect(JSON.parse(String(requests[0].body)).task_mode).toBe(true);
  }
});

it.each(['task', 'stream'] as const)('%s never sends if canceled while waiting for the tenant', async kind => {
  const handle = start(kind);
  handle.close();
  await act(async () => { resolveScope({ 'X-Management-Tenant': '25' }); });
  expect(requests).toHaveLength(0);
});

it.each(['task', 'stream'] as const)('%s reports tenant bootstrap failure without submitting a question', async kind => {
  const handle = start(kind);
  await act(async () => { rejectScope(new Error('scope unavailable')); });
  expect(requests).toHaveLength(0);
  expect(handle.onError).toHaveBeenCalledTimes(1);
  expect(handle.onEnd).toHaveBeenCalledTimes(1);
});
