/** @jest-environment jsdom */
import { renderHook } from '@testing-library/react';
import {
  resendConversationActivity,
  resetDesktopConversationBridge,
  useDesktopConversationActivity,
  useDesktopConversationRenamed,
} from './desktopConversationBridge';

let mockChannel = 'desktop';
jest.mock('~/utils/clientEnvironment', () => {
  const actual = jest.requireActual('~/utils/clientEnvironment');
  // React snapshots must stay stable between reads, so reuse one object per channel.
  const snapshots = new Map();
  const getClientEnvironment = () => {
    const base = actual.getClientEnvironment();
    const cached = snapshots.get(mockChannel);
    if (cached?.base === base) return cached.value;
    const value = { ...base, channel: mockChannel };
    snapshots.set(mockChannel, { base, value });
    return value;
  };
  return { ...actual, getClientEnvironment };
});

beforeEach(() => {
  resetDesktopConversationBridge();
  mockChannel = 'desktop';
});
afterEach(() => {
  delete window.dshChatPresentation;
});

describe('useDesktopConversationActivity', () => {
  it('reports the union of every chat instance once per change and releases on unmount', () => {
    const reportRunning = jest.fn();
    window.dshChatPresentation = { reportLanding: jest.fn(), reportRunning };
    const first = renderHook(({ ids }) => useDesktopConversationActivity('owner-a', ids), {
      initialProps: { ids: ['chat-a'] },
    });
    const second = renderHook(() => useDesktopConversationActivity('owner-b', ['chat-b', 'chat-a']));
    expect(reportRunning.mock.calls).toEqual([[['chat-a']], [['chat-a', 'chat-b']]]);
    // A re-render with the same running set stays quiet.
    first.rerender({ ids: ['chat-a', 'chat-a'] });
    expect(reportRunning).toHaveBeenCalledTimes(2);
    second.unmount();
    expect(reportRunning).toHaveBeenLastCalledWith(['chat-a']);
    first.rerender({ ids: [] });
    expect(reportRunning).toHaveBeenLastCalledWith([]);
    expect(reportRunning).toHaveBeenCalledTimes(4);
  });

  it('stays silent outside the desktop and tolerates hosts without activity support', () => {
    mockChannel = 'web';
    const reportRunning = jest.fn();
    window.dshChatPresentation = { reportLanding: jest.fn(), reportRunning };
    renderHook(() => useDesktopConversationActivity('owner-a', ['chat-a']));
    resendConversationActivity();
    expect(reportRunning).not.toHaveBeenCalled();
    mockChannel = 'desktop';
    window.dshChatPresentation = { reportLanding: jest.fn() };
    expect(() => renderHook(() => useDesktopConversationActivity('owner-b', ['chat-b']))).not.toThrow();
  });

  it('re-sends the current list after navigation, but only once something was reported', () => {
    const reportRunning = jest.fn();
    window.dshChatPresentation = { reportLanding: jest.fn(), reportRunning };
    resendConversationActivity();
    expect(reportRunning).not.toHaveBeenCalled();
    renderHook(() => useDesktopConversationActivity('owner-a', ['chat-a']));
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
    mockChannel = 'web';
    const onConversationRenamed = jest.fn(() => () => {});
    window.dshChatPresentation = { reportLanding: jest.fn(), onConversationRenamed };
    renderHook(() => useDesktopConversationRenamed(jest.fn()));
    expect(onConversationRenamed).not.toHaveBeenCalled();
    mockChannel = 'desktop';
    window.dshChatPresentation = { reportLanding: jest.fn() };
    expect(() => renderHook(() => useDesktopConversationRenamed(jest.fn()))).not.toThrow();
  });
});
