import { act, renderHook, waitFor } from '@testing-library/react';
import { normalizeApiError } from '@bisheng/api-client';
import useFileChat from './useFileChat';
import useChannelChat from './useChannelChat';
import useFolderChat from './useFolderChat';
import * as api from '~/api/chatApi';
jest.mock('~/api/chatApi', () => ({ getFileChatHistory: jest.fn(), clearFileChatHistory: jest.fn(), getChannelChatHistory: jest.fn(), clearChannelChat: jest.fn(), getFolderSessions: jest.fn(), getFolderChatHistory: jest.fn(), deleteFolderSession: jest.fn() }));
jest.mock('~/api/request', () => ({ showApiError: jest.fn() }));
jest.mock('recoil', () => ({ useRecoilValue: () => ({ id: 1, name: 'Model' }) }));
jest.mock('~/store', () => ({ __esModule: true, default: { chatModel: 'model' } }));
jest.mock('./useStreamChatSSE', () => ({ __esModule: true, default: () => ({ abort: jest.fn() }) }));
const message = (text: string) => [{ text, messageId: text }];
beforeEach(() => jest.resetAllMocks());
const cases = [
  { name: 'file', useChat: (id: string) => useFileChat('space', id), history: api.getFileChatHistory, clear: api.clearFileChatHistory },
  { name: 'article', useChat: (id: string) => useChannelChat(id), history: api.getChannelChatHistory, clear: api.clearChannelChat },
];
describe.each(cases)('$name history request ownership', ({ useChat, history, clear }) => {
  it('does not clear the new resource when an old resource deletion completes late', async () => {
    let finish: () => void = () => undefined;
    (history as jest.Mock).mockResolvedValueOnce(message('A')).mockResolvedValueOnce(message('B'));
    (clear as jest.Mock).mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
    const { result, rerender } = renderHook(({ id }) => useChat(id), { initialProps: { id: 'A' } });
    await waitFor(() => expect(result.current.messages[0]?.text).toBe('A'));
    act(() => result.current.clearConversation());
    rerender({ id: 'B' });
    await waitFor(() => expect(result.current.messages[0]?.text).toBe('B'));
    await act(async () => { finish(); });
    expect(result.current.messages[0]?.text).toBe('B');
    expect(result.current.isClearing).toBe(false);
  });
  it('blocks duplicate clears and new turns while deletion is pending', async () => {
    let finish: () => void = () => undefined;
    (history as jest.Mock).mockResolvedValue(message('kept'));
    (clear as jest.Mock).mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
    const { result } = renderHook(() => useChat('A'));
    await waitFor(() => expect(result.current.messages[0]?.text).toBe('kept'));
    act(() => { result.current.clearConversation(); result.current.clearConversation(); result.current.sendMessage('new turn'); });
    expect(clear).toHaveBeenCalledTimes(1);
    expect(result.current.isClearing).toBe(true);
    expect(result.current.messages).toHaveLength(1);
    await act(async () => { finish(); });
    expect(result.current.isClearing).toBe(false);
    expect(result.current.messages).toHaveLength(0);
  });
  it('keeps messages when clearing fails', async () => {
    (history as jest.Mock).mockResolvedValue(message('kept'));
    (clear as jest.Mock).mockRejectedValue(new Error('clear unavailable'));
    const { result } = renderHook(() => useChat('A'));
    await waitFor(() => expect(result.current.messages[0]?.text).toBe('kept'));
    await act(async () => { result.current.clearConversation(); });
    expect(result.current.messages[0]?.text).toBe('kept');
  });
  it('retains history failure until retry succeeds', async () => {
    const failure = normalizeApiError(new Error('history unavailable'), { message: 'history unavailable' });
    (history as jest.Mock).mockRejectedValueOnce(failure).mockResolvedValueOnce(message('restored'));
    const { result } = renderHook(() => useChat('A'));
    await waitFor(() => expect(result.current.historyError).toBe(failure));
    act(() => result.current.retryHistory());
    await waitFor(() => expect(result.current.messages[0]?.text).toBe('restored'));
    expect(result.current.historyError).toBeNull();
  });
});
it('does not clear a new folder session when a previous session deletion completes late', async () => {
  let finish: () => void = () => undefined;
  (api.getFolderSessions as jest.Mock).mockImplementation(async space => [{ chat_id: space }]);
  (api.getFolderChatHistory as jest.Mock).mockImplementation(async space => message(space));
  (api.deleteFolderSession as jest.Mock).mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
  const { result, rerender } = renderHook(({ space }) => useFolderChat(space), { initialProps: { space: 'A' } });
  await waitFor(() => expect(result.current.messages[0]?.text).toBe('A'));
  act(() => result.current.clearConversation());
  rerender({ space: 'B' });
  await waitFor(() => expect(result.current.messages[0]?.text).toBe('B'));
  await act(async () => { finish(); });
  expect(result.current.messages[0]?.text).toBe('B');
  expect(result.current.activeChatId).toBe('B');
  expect(result.current.isClearing).toBe(false);
  expect(result.current.sessions).toEqual([{ chat_id: 'B' }]);
});
