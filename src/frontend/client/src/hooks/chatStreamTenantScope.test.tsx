import { act, renderHook } from '@testing-library/react';
import { prepareBrowserHeaders } from '~/api/request';
import useStreamChatSSE, { type StreamChatSSESubmission } from './useStreamChatSSE';

// Keep the real SSE library: its default constructor sends immediately.
jest.mock('~/api/request', () => ({ prepareBrowserHeaders: jest.fn(), translateApiErrorMessage: () => '' }));

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

function start() {
  const onError = jest.fn();
  const onEnd = jest.fn();
  const submission: StreamChatSSESubmission = {
    sseUrl: '/workspace/api/v1/channel/chat', payload: { question: 'Question' },
    onStart: jest.fn(), onMessage: jest.fn(), onFinal: jest.fn(), onError, onEnd,
  };
  const hook = renderHook(() => useStreamChatSSE(submission));
  cleanups.push(hook.unmount);
  return { close: hook.unmount, onError, onEnd };
}

it('sends only once after the tenant proof is ready', async () => {
  start();
  expect(requests).toHaveLength(0);
  await act(async () => { resolveScope({ 'X-Management-Tenant': '25' }); });
  expect(requests).toHaveLength(1);
  expect(requests[0].headers).toMatchObject({ 'Content-Type': 'application/json', 'X-Management-Tenant': '25' });
});

it('never sends if canceled while waiting for the tenant', async () => {
  const handle = start();
  handle.close();
  await act(async () => { resolveScope({ 'X-Management-Tenant': '25' }); });
  expect(requests).toHaveLength(0);
});

it('reports tenant bootstrap failure without submitting a question', async () => {
  const handle = start();
  await act(async () => { rejectScope(new Error('scope unavailable')); });
  expect(requests).toHaveLength(0);
  expect(handle.onError).toHaveBeenCalledTimes(1);
  expect(handle.onEnd).toHaveBeenCalledTimes(1);
});
