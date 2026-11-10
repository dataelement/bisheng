import { QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createPlatformQueryClient } from '@/queryClient';
import { useModel } from './index';

const mock = vi.hoisted(() => ({ llm: vi.fn(), assistant: vi.fn(), user: 'user:7', tenant: 101, pin: null as number | null }));
vi.mock('@/hooks/useKnowledgePageScope', () => ({ useKnowledgePageScope: () => ({ scopes: { ordinary: { identityKey: mock.user, tenantId: mock.tenant, managementTenantId: mock.tenant } } }) }));
vi.mock('@/controllers/managementScope', () => ({ managementRequestScope: () => mock.pin }));
vi.mock('@/controllers/API/finetune', () => ({ getModelListApi: mock.llm, getAssistantModelList: mock.assistant, changeLLmServerStatus: vi.fn(), verifyLLmModelStatus: vi.fn() }));
vi.mock('./ModelConfig', () => ({ default: () => null }));
vi.mock('./ModelProviderRow', () => ({ ModelProviderRow: () => null }));
vi.mock('./SystemModelConfig', () => ({ default: () => null }));
beforeEach(() => {
  mock.user = 'user:7'; mock.tenant = 101; mock.pin = null;
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
  expect(client.getQueryData(['QueryModelsKey', 'user:7', 101, 101, null])).toEqual([expect.objectContaining({ id: 1 })]);
  expect(client.getQueryData(['QueryAssistantModelsKey', 'user:7', 101, 101, null])).toEqual([expect.objectContaining({ id: 2 })]);
  await act(async () => { await client.invalidateQueries({ queryKey: ['QueryModelsKey'] }); });
  expect(mock.llm).toHaveBeenCalledTimes(2);
  expect(mock.assistant).toHaveBeenCalledTimes(1);
  act(() => { client.removeQueries({ queryKey: ['QueryAssistantModelsKey'] }); });
  expect(client.getQueryData(['QueryAssistantModelsKey', 'user:7', 101, 101, null])).toBeUndefined();
  expect(client.getQueryData(['QueryModelsKey', 'user:7', 101, 101, null])).toBeTruthy();
  client.clear();
});

it('does not expose a pending old identity model response in the next tenant', async () => {
  const client = createPlatformQueryClient();
  let resolve!: (value: unknown) => void;
  mock.llm.mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValueOnce([{ id: 2, name: 'New tenant', models: [{ id: 22, model_name: 'New model', model_type: 'llm', online: true }] }]);
  const { result, rerender } = renderHook(() => useModel(), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  await waitFor(() => expect(mock.llm).toHaveBeenCalledOnce());
  mock.user = 'user:8'; mock.tenant = 202; mock.pin = 202;
  rerender();
  await waitFor(() => expect(result.current.llmOptions).toEqual([expect.objectContaining({ label: 'New tenant' })]));
  await act(async () => resolve([{ id: 1, name: 'Old private name', models: [{ id: 11, model_name: 'Old private model', model_type: 'llm', online: true }] }]));
  expect(result.current.llmOptions).toEqual([expect.objectContaining({ label: 'New tenant' })]);
  client.clear();
});
