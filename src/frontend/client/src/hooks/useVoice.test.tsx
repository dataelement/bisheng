import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { PropsWithChildren } from 'react';
import request from '~/api/request';
import { getWorkbenchModelListApi } from '~/api';
import { StandaloneChatContext, type StandaloneChatContextValue } from '~/pages/standaloneChat/StandaloneChatContext';
import { QueryKeys } from '~/types/chat/keys';
import { useVoiceModels } from './useVoice';

jest.mock('~/api', () => ({ getWorkbenchModelListApi: jest.fn() }));
jest.mock('~/api/request', () => ({ __esModule: true, default: { get: jest.fn() } }));

test.each(['workflow', 'assistant'] as const)('guest %s configuration cannot reuse authenticated or other app data', async (flowType) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData([QueryKeys.getWorkspaceModel], { data: { tts_model: { id: 'private' } } });
  let flowId = 'first';
  jest.mocked(request.get)
    .mockResolvedValueOnce({ data: { asr_model: { id: 'first-asr' }, tts_model: { id: null } } })
    .mockResolvedValueOnce({ data: { asr_model: { id: 'second-asr' }, tts_model: { id: null } } });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>
      <StandaloneChatContext.Provider value={{ mode: 'guest', flowType, flowId, apiVersion: 'v3', autoRerunOnOpen: false }}>
        {children}
      </StandaloneChatContext.Provider>
    </QueryClientProvider>
  );
  const { result, rerender, unmount } = renderHook(() => useVoiceModels(), { wrapper });
  await waitFor(() => expect(result.current.data?.asr_model?.id).toBe('first-asr'));
  flowId = 'second';
  rerender();
  await waitFor(() => expect(result.current.data?.asr_model?.id).toBe('second-asr'));
  expect(result.current.data?.tts_model?.id).toBeNull();
  expect(getWorkbenchModelListApi).not.toHaveBeenCalled();
  expect(request.get).toHaveBeenCalledWith('/api/v3/llm/workbench?flow_id=first', { skip403Redirect: true });
  expect(request.get).toHaveBeenCalledWith('/api/v3/llm/workbench?flow_id=second', { skip403Redirect: true });
  unmount();
  client.clear();
});

test('guest controls wait for an application instead of fetching authenticated config', () => {
  const client = new QueryClient();
  const context: StandaloneChatContextValue = {
    mode: 'guest', flowType: 'workflow', flowId: '', apiVersion: 'v3', autoRerunOnOpen: false,
  };
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>
      <StandaloneChatContext.Provider value={context}>{children}</StandaloneChatContext.Provider>
    </QueryClientProvider>
  );
  const { result, unmount } = renderHook(() => useVoiceModels(), { wrapper });
  expect(result.current.fetchStatus).toBe('idle');
  expect(request.get).not.toHaveBeenCalled();
  expect(getWorkbenchModelListApi).not.toHaveBeenCalled();
  unmount();
  client.clear();
});
