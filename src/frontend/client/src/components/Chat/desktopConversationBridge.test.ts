/** @jest-environment jsdom */
import { renderHook } from '@testing-library/react';
import type { LinsightInfo } from '~/store/linsight';
import {
  resendConversationActivity,
  resetDesktopConversationBridge,
  runningConversationIds,
  useDesktopConversationActivity,
  useDesktopConversationRenamed,
} from './desktopConversationBridge';

const task = (session_id: string, status: string, sessionSteps: unknown[] = []) =>
  ({ session_id, status, sessionSteps, tasks: [] }) as unknown as LinsightInfo;
const tasks = (...rows: LinsightInfo[]) => new Map(rows.map((row, index) => [`version-${index}`, row]));
const NO_TASKS = tasks();

beforeEach(() => {
  resetDesktopConversationBridge();
  window.sessionStorage.setItem('dsh:embedded-chat', 'true');
});
afterEach(() => {
  delete window.dshChatPresentation;
  window.sessionStorage.clear();
});

describe('runningConversationIds', () => {
  it('combines streaming answers with task runs that still drive the spinner', () => {
    const ids = runningConversationIds(
      { 'chat-b': true, 'chat-a': true, 'chat-idle': false, new: true, 'bad id': true },
      tasks(
        task('task-running', 'running'),
        task('task-starting', 'not_started'),
        task('task-done', 'completed'),
        task('task-parked', 'running', [{ step_type: 'call_user_input', is_completed: false }]),
        task('chat-a', 'sopGenerating'),
      ),
    );
    expect(ids).toEqual(['chat-a', 'chat-b', 'task-running', 'task-starting']);
  });
});

describe('useDesktopConversationActivity', () => {
  it('reports the union of every chat instance once per change and releases on unmount', () => {
    const reportRunning = jest.fn();
    window.dshChatPresentation = { reportLanding: jest.fn(), reportRunning };
    const first = renderHook(({ streaming }) => useDesktopConversationActivity('owner-a', streaming, NO_TASKS), {
      initialProps: { streaming: { 'chat-a': true } as Record<string, boolean> },
    });
    const second = renderHook(() => useDesktopConversationActivity('owner-b', { 'chat-a': true, 'chat-b': true }, NO_TASKS));
    expect(reportRunning.mock.calls).toEqual([[['chat-a']], [['chat-a', 'chat-b']]]);
    // A re-render with the same running set stays quiet.
    first.rerender({ streaming: { 'chat-a': true, 'chat-z': false } });
    expect(reportRunning).toHaveBeenCalledTimes(2);
    second.unmount();
    expect(reportRunning).toHaveBeenLastCalledWith(['chat-a']);
    first.rerender({ streaming: { 'chat-a': false } });
    expect(reportRunning).toHaveBeenLastCalledWith([]);
    expect(reportRunning).toHaveBeenCalledTimes(4);
  });

  it('reports task-mode runs and stops when the run finishes', () => {
    const reportRunning = jest.fn();
    window.dshChatPresentation = { reportLanding: jest.fn(), reportRunning };
    const { rerender } = renderHook(({ map }) => useDesktopConversationActivity('owner-a', {}, map), {
      initialProps: { map: tasks(task('chat-task', 'running')) },
    });
    expect(reportRunning).toHaveBeenLastCalledWith(['chat-task']);
    rerender({ map: tasks(task('chat-task', 'completed')) });
    expect(reportRunning).toHaveBeenLastCalledWith([]);
  });

  it('stays silent outside the desktop and tolerates hosts without activity support', () => {
    window.sessionStorage.clear();
    const reportRunning = jest.fn();
    window.dshChatPresentation = { reportLanding: jest.fn(), reportRunning };
    renderHook(() => useDesktopConversationActivity('owner-a', { 'chat-a': true }, NO_TASKS));
    resendConversationActivity();
    expect(reportRunning).not.toHaveBeenCalled();
    window.sessionStorage.setItem('dsh:embedded-chat', 'true');
    window.dshChatPresentation = { reportLanding: jest.fn() };
    expect(() => renderHook(() => useDesktopConversationActivity('owner-b', { 'chat-b': true }, NO_TASKS))).not.toThrow();
  });

  it('re-sends the current list after navigation, but only once something was reported', () => {
    const reportRunning = jest.fn();
    window.dshChatPresentation = { reportLanding: jest.fn(), reportRunning };
    resendConversationActivity();
    expect(reportRunning).not.toHaveBeenCalled();
    renderHook(() => useDesktopConversationActivity('owner-a', { 'chat-a': true }, NO_TASKS));
    resendConversationActivity();
    expect(reportRunning.mock.calls).toEqual([[['chat-a']], [['chat-a']]]);
  });
});

describe('useDesktopConversationRenamed', () => {
  it('subscribes once, calls the latest handler and unsubscribes on unmount', () => {
    let listener: ((conversationId: string) => void) | undefined;
    const unsubscribe = jest.fn();
    const onConversationRenamed = jest.fn((next: (conversationId: string) => void) => { listener = next; return unsubscribe; });
    window.dshChatPresentation = { reportLanding: jest.fn(), onConversationRenamed };
    const first = jest.fn();
    const latest = jest.fn();
    const { rerender, unmount } = renderHook(({ handler }) => useDesktopConversationRenamed(handler), { initialProps: { handler: first } });
    rerender({ handler: latest });
    listener?.('chat-a');
    expect(first).not.toHaveBeenCalled();
    expect(latest).toHaveBeenCalledWith('chat-a');
    expect(onConversationRenamed).toHaveBeenCalledTimes(1);
    unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });

  it('does nothing outside the desktop or on hosts without rename support', () => {
    window.sessionStorage.clear();
    const onConversationRenamed = jest.fn(() => () => {});
    window.dshChatPresentation = { reportLanding: jest.fn(), onConversationRenamed };
    renderHook(() => useDesktopConversationRenamed(jest.fn()));
    expect(onConversationRenamed).not.toHaveBeenCalled();
    window.sessionStorage.setItem('dsh:embedded-chat', 'true');
    window.dshChatPresentation = { reportLanding: jest.fn() };
    expect(() => renderHook(() => useDesktopConversationRenamed(jest.fn()))).not.toThrow();
  });
});
