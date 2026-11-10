import { act, renderHook } from '@testing-library/react';
import { type ReactNode, useState } from 'react';
// eslint-disable-next-line no-restricted-imports -- 覆盖现有会话 WebSocket 入口。
import { RecoilRoot, useSetRecoilState } from 'recoil';
import { type AgentLongTaskStatus, closeAppChatWebSocket, useWebSocket } from './useWebsocket';
import { submitDataState } from './store/atoms';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useToast: () => ({ showToast: jest.fn() }) }));
jest.mock('~/api/chat/data-service', () => ({ genTitle: jest.fn() }));
jest.mock('~/utils', () => ({ generateUUID: () => 'answer-operation' }));
jest.mock('~/pages/standaloneChat/StandaloneChatContext', () => ({ useOptionalStandaloneChatContext: () => null }));

class Socket {
  static OPEN = 1;
  static CONNECTING = 0;
  static latest: Socket;
  readyState = 1;
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  onclose?: (event: { code: number }) => void;
  onerror?: () => void;
  send = jest.fn();
  constructor() { Socket.latest = this; }
  close() { this.readyState = 3; this.onclose?.({ code: 1006 }); }
  receive(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }); }
}

const view = {
  execution_id: 'original', interaction_id: 'form-1', revision: 'opaque', status_version: 1,
  phase: 'WAITING_INPUT', expires_at: '2099-01-01T00:00:00Z',
  form: { type: 'text', label: 'Details', required: true, max_length: 20 },
};

function mount(chatId: string, isNew = false) {
  const helpers = {
    chatId, wsUrl: 'localhost/session', flow: { flow_type: 10, id: 'workflow', isNew },
    clearError: jest.fn(), handleMsgError: jest.fn(), stopShow: jest.fn(), showInputForm: jest.fn(), reRunShow: jest.fn(),
    message: { closeAllMsg: jest.fn(), stopMsg: jest.fn(), closeAllLogMsg: jest.fn(), insetSeparator: jest.fn() },
  };
  const wrapper = ({ children }: { children: ReactNode }) => <RecoilRoot>{children}</RecoilRoot>;
  const hook = renderHook(() => {
    const [longStatus, setLongStatus] = useState<AgentLongTaskStatus | null>(null);
    return { ...useWebSocket(helpers, { onLongTaskStatus: (_, status) => setLongStatus(status) }),
      longStatus, stop: useSetRecoilState(submitDataState) };
  }, { wrapper });
  act(() => Socket.latest.onopen?.());
  const receive = (message: unknown, socket = Socket.latest) => {
    act(() => socket.receive({ category: 'processing', type: 'info', chat_id: chatId, message }));
  };
  return { ...hook, helpers, receive, cleanup: () => { hook.unmount(); closeAppChatWebSocket(chatId); } };
}

beforeEach(() => {
  jest.useFakeTimers();
  Object.defineProperty(window, 'WebSocket', { configurable: true, value: Socket });
});
afterEach(() => jest.useRealTimers());

test('marks an empty history connection as a passive initial open', () => {
  const app = mount('interaction-initial-open', true);
  expect(JSON.parse(Socket.latest.send.mock.calls[0][0])).toMatchObject({
    action: 'init_data', chat_id: 'interaction-initial-open', initial_open: true,
  });
  app.cleanup();
});

test('authorizes a worker hint through status, reconnects and reuses the submission ID', () => {
  const app = mount('interaction-reconnect');
  const first = Socket.latest;
  app.receive({ agent_long_task: {
    execution_id: 'original', interaction_pending: true,
    local_state: 'WAITING_RESULT', remote_state: 'WAITING_INPUT', cancel_state: 'NONE',
  } });
  expect(JSON.parse(first.send.mock.calls.at(-1)![0])).toMatchObject({ action: 'check_status', execution_id: 'original' });
  expect(app.result.current.interaction).toBeUndefined();
  app.receive({ agent_interaction: view });
  expect(app.result.current.interaction?.form?.label).toBe('Details');
  act(() => app.result.current.submitInteraction('My answer'));
  const sent = JSON.parse(first.send.mock.calls.at(-1)![0]);
  expect(sent).toMatchObject({ action: 'agent_interaction_submit', execution_id: 'original', answer: 'My answer', submission_id: 'answer-operation' });
  act(() => { first.close(); jest.advanceTimersByTime(1000); });
  const reopened = Socket.latest;
  expect(reopened).not.toBe(first);
  act(() => reopened.onopen?.());
  expect(JSON.parse(reopened.send.mock.calls.at(-1)![0])).toMatchObject({ action: 'check_status', execution_id: 'original' });
  app.receive({ agent_interaction: view });
  expect(JSON.parse(reopened.send.mock.calls.at(-1)![0])).toEqual(sent);
  app.receive({ agent_interaction: { ...view, status_version: 2, phase: 'SUBMIT_QUEUED', form: undefined } });
  app.receive({ agent_interaction: view });
  expect(app.result.current.interaction?.phase).toBe('SUBMIT_QUEUED');
  expect(app.result.current.interaction?.form).toBeUndefined();
  app.cleanup();
});

test('stopping hides the form and keeps native input on its existing path', () => {
  const app = mount('interaction-stop');
  app.receive({ agent_interaction: view });
  act(() => app.result.current.stop({ action: 'stop' }));
  expect(JSON.parse(Socket.latest.send.mock.calls.at(-1)![0])).toMatchObject({ action: 'stop', execution_id: 'original' });
  app.receive({ agent_interaction: view });
  expect(app.result.current.interaction?.form).toBeUndefined();
  app.cleanup();

  const native = mount('native-input');
  act(() => Socket.latest.receive({ category: 'input', chat_id: 'native-input', message: { node_id: 'native', input_schema: { key: 'value' } } }));
  expect(native.helpers.showInputForm).toHaveBeenCalledWith({ node_id: 'native', key: 'value' });
  expect(native.result.current.interaction).toBeUndefined();
  native.cleanup();
});

test('a stop during disconnection takes precedence over resending the pending answer', () => {
  const app = mount('interaction-offline-stop');
  const first = Socket.latest;
  app.receive({ agent_interaction: view });
  act(() => app.result.current.submitInteraction('My answer'));
  act(() => first.close());
  act(() => app.result.current.stop({ action: 'stop' }));
  expect(app.result.current.interaction?.form).toBeUndefined();
  act(() => jest.advanceTimersByTime(1000));
  const reopened = Socket.latest;
  act(() => reopened.onopen?.());
  expect(reopened.send).toHaveBeenCalledWith(JSON.stringify({ action: 'stop', execution_id: 'original' }));
  app.receive({ agent_interaction: view });
  expect(reopened.send.mock.calls.map(([body]) => JSON.parse(body).action)).not.toContain('agent_interaction_submit');
  app.cleanup();
});

test('a rejected submission refreshes the original form without resetting its version fence', () => {
  const app = mount('interaction-rejected-submit');
  const socket = Socket.latest;
  app.receive({ agent_interaction: view });
  act(() => app.result.current.submitInteraction('My answer'));
  act(() => socket.receive({ category: 'error', type: 'over', chat_id: 'interaction-rejected-submit',
    message: { status_code: 10560, agent_interaction_error: 'retry' } }));
  expect(socket.send).toHaveBeenLastCalledWith(expect.stringContaining('"action":"check_status"'));
  expect(app.result.current.interaction?.form).toBeUndefined();
  app.receive({ agent_interaction: view });
  expect(app.result.current.interaction?.form?.label).toBe('Details');
  expect(() => act(() => app.result.current.submitInteraction('Corrected answer'))).not.toThrow();
  app.cleanup();
});

test('a denied status hides the form and stops polling and accepting buffered frames', () => {
  const chatId = 'interaction-revoked-status';
  const app = mount(chatId);
  const socket = Socket.latest;
  app.receive({ agent_interaction: view });
  act(() => socket.receive({ category: 'error', type: 'over', chat_id: chatId,
    message: { status_code: 10555, execution_id: view.execution_id, agent_interaction_error: 'blocked' } }));
  app.receive({ agent_interaction: view });
  const count = socket.send.mock.calls.length;
  act(() => jest.advanceTimersByTime(3000));
  expect(socket.send).toHaveBeenCalledTimes(count);
  expect(app.result.current.interaction).toBeUndefined();
  expect(() => app.result.current.submitInteraction('Protected')).toThrow();
  app.cleanup();
});

test('a plain long task reconnects to the original run and polls until cancellation is confirmed', () => {
  const app = mount('agent-long-task');
  const running = { execution_id: 'original', local_state: 'WAITING_RESULT', remote_state: 'RUNNING',
    cancel_state: 'NONE', status_version: 3, deadline: 2000 };
  const first = Socket.latest;
  app.receive({ agent_long_task: running });
  expect(app.result.current.interaction).toBeUndefined();
  act(() => { first.close(); jest.advanceTimersByTime(1000); });
  const reopened = Socket.latest;
  expect(reopened).not.toBe(first);
  act(() => reopened.onopen?.());
  expect(reopened.send).toHaveBeenLastCalledWith(expect.stringContaining('"execution_id":"original"'));
  act(() => app.result.current.stop({ action: 'stop' }));
  expect(reopened.send).toHaveBeenLastCalledWith(JSON.stringify({ action: 'stop', execution_id: 'original' }));
  app.receive({ agent_long_task: { ...running, status_version: 4, local_state: 'STOPPED', cancel_state: 'ACCEPTED' } });
  app.receive({ agent_long_task: { ...running, status_version: 2 } });
  expect(app.result.current.longStatus).toMatchObject({ local_state: 'STOPPED', cancel_state: 'ACCEPTED' });
  act(() => jest.advanceTimersByTime(1000));
  expect(reopened.send).toHaveBeenLastCalledWith(expect.stringContaining('"action":"check_status"'));
  app.receive({ agent_long_task: { ...running, status_version: 5, local_state: 'STOPPED',
    remote_state: 'CANCELLED', cancel_state: 'CONFIRMED' } });
  const count = reopened.send.mock.calls.length;
  act(() => jest.advanceTimersByTime(2000));
  expect(reopened.send).toHaveBeenCalledTimes(count);
  app.cleanup();
});
