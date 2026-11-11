import { act, renderHook, waitFor } from '@testing-library/react';
import useFileChat from './useFileChat';
import useChannelChat from './useChannelChat';
import useStreamChatSSE, { type StreamChatSSESubmission } from './useStreamChatSSE';
import * as api from '~/api/chatApi';

jest.mock('~/api/chatApi', () => ({
  getFileChatHistory: jest.fn(), getChannelChatHistory: jest.fn(),
  getFileChatSSEUrl: jest.fn(), getChannelSSEUrl: jest.fn(),
}));
jest.mock('~/api/request', () => ({ showApiError: jest.fn() }));
jest.mock('recoil', () => ({ useRecoilValue: () => ({ id: 1, name: 'Model' }) }));
jest.mock('~/store', () => ({ __esModule: true, default: { chatModel: 'model' } }));
jest.mock('./useStreamChatSSE', () => ({ __esModule: true, default: jest.fn(() => ({ abort: jest.fn() })) }));

beforeEach(() => {
  jest.clearAllMocks();
  (api.getFileChatHistory as jest.Mock).mockResolvedValue([]);
  (api.getChannelChatHistory as jest.Mock).mockResolvedValue([]);
});

it.each([
  { name: 'file', useChat: () => useFileChat('4064', '97428') },
  { name: 'article', useChat: () => useChannelChat('article') },
])('retains final citations in $name answers before reloading', async ({ useChat }) => {
  const { result } = renderHook(() => {
    const { isLoading, messages, sendMessage } = useChat();
    return { isLoading, messages, sendMessage };
  });
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  await act(async () => { result.current.sendMessage('Question'); });
  const calls = (useStreamChatSSE as jest.Mock).mock.calls;
  const submission = calls[calls.length - 1][0] as StreamChatSSESubmission;
  const citations = [{ citationId: 'knowledgesearch_15c85c1a', type: 'rag', itemId: '29' }];
  act(() => submission.onFinal('Answer knowledgesearch_15c85c1a:29', 442820, citations));
  const answer = result.current.messages.find(message => message.messageId === '442820');
  expect(answer?.citations).toEqual(citations);
  expect(answer?.text).toBe('Answer knowledgesearch_15c85c1a:29');
});
