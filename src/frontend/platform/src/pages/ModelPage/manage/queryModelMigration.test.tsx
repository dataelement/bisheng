import { QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createPlatformQueryClient } from '@/queryClient';
import { useModel } from './index';

const mock = vi.hoisted(() => ({ llm: vi.fn(), assistant: vi.fn() }));
vi.mock('@/controllers/API/finetune', () => ({ getModelListApi: mock.llm, getAssistantModelList: mock.assistant, changeLLmServerStatus: vi.fn(), verifyLLmModelStatus: vi.fn() }));
vi.mock('./ModelConfig', () => ({ default: () => null }));
vi.mock('./ScopeBar', () => ({ ScopeBar: () => null }));
vi.mock('./ModelProviderRow', () => ({ ModelProviderRow: () => null }));
vi.mock('./SystemModelConfig', () => ({ default: () => null }));
beforeEach(() => {
  mock.llm.mockReset(); mock.assistant.mockReset();
  mock.llm.mockResolvedValue([{ id: 1, name: 'LLM provider', models: [{ id: 11, model_name: 'Chat', model_type: 'llm', online: true }] }]);
  mock.assistant.mockResolvedValue([{ id: 2, name: 'Assistant provider', models: [{ id: 22, model_name: 'Assistant', model_type: 'llm', online: true }] }]);
});
afterEach(cleanup);

it('keeps model types in separate array-key caches and refreshes only the selected type', async () => {
  const client = createPlatformQueryClient();
  const { result } = renderHook(() => ({ llm: useModel(), assistant: useModel('assistant') }), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  await waitFor(() => {
    expect(result.current.llm.llmOptions).toHaveLength(1);
    expect(result.current.assistant.llmOptions).toHaveLength(1);
  });
  expect(client.getQueryData(['QueryModelsKey'])).toEqual([expect.objectContaining({ id: 1 })]);
  expect(client.getQueryData(['QueryAssistantModelsKey'])).toEqual([expect.objectContaining({ id: 2 })]);
  await act(async () => { await client.invalidateQueries({ queryKey: ['QueryModelsKey'] }); });
  expect(mock.llm).toHaveBeenCalledTimes(2);
  expect(mock.assistant).toHaveBeenCalledTimes(1);
  act(() => { client.removeQueries({ queryKey: ['QueryAssistantModelsKey'] }); });
  expect(client.getQueryData(['QueryAssistantModelsKey'])).toBeUndefined();
  expect(client.getQueryData(['QueryModelsKey'])).toBeTruthy();
  client.clear();
});
