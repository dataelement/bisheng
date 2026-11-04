import { normalizeApiError } from '@bisheng/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useWorkbenchRuntimeConfig } from './useWorkbenchRuntimeConfig';

const mock = vi.hoisted(() => ({ get: vi.fn(), showError: vi.fn() }));
vi.mock('@/controllers/request', () => ({ default: { get: mock.get }, showApiError: mock.showError }));
beforeEach(() => { mock.get.mockReset(); mock.showError.mockReset(); });
afterEach(cleanup);

function open() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } } });
  client.setQueryData(['linsightModelEnvelope'], { data: { asr_model: { id: 'admin-only' } } });
  const hook = renderHook(() => useWorkbenchRuntimeConfig(), {
    wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  return { ...hook, client };
}

it('reads the runtime endpoint and never reuses cached model settings', async () => {
  mock.get.mockResolvedValue({ data: { asr_model: { id: 'runtime-asr' }, tts_model: { id: 'runtime-tts' } }, inherited_from_root: true, fallback_blocked: false });
  const { result, client } = open();
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(mock.get).toHaveBeenCalledWith('/api/v1/llm/workbench');
  expect(result.current.data).toMatchObject({ asr_model: { id: 'runtime-asr' }, tts_model: { id: 'runtime-tts' } });
  expect(mock.get).toHaveBeenCalledTimes(1);
  client.clear();
});

it('keeps runtime failures as errors instead of falling back to admin configuration', async () => {
  const error = normalizeApiError({ status_code: 19002 }, { message: 'Runtime config unavailable' });
  mock.get.mockRejectedValue(error);
  const { result, client } = open();
  await waitFor(() => expect(result.current.isError).toBe(true));
  expect(result.current.data).toBeUndefined();
  expect(mock.showError).toHaveBeenCalledWith(error);
  expect(mock.get.mock.calls.every(([path]) => path === '/api/v1/llm/workbench')).toBe(true);
  client.clear();
});
