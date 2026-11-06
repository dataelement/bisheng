import { normalizeApiError } from '@bisheng/api-client';
import { QueryClientProvider } from '@tanstack/react-query';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createPlatformQueryClient } from '@/queryClient';
import { useLinsightConfig } from './WorkbenchModel';

const mock = vi.hoisted(() => ({ load: vi.fn(), handle: vi.fn() }));
vi.mock('@/controllers/API/finetune', () => ({ getLinsightModelEnvelope: mock.load, updateLinsightModelConfig: vi.fn() }));
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: mock.handle, showApiError: mock.handle }));
vi.mock('@/pages/ModelPage/manage', () => ({ useModel: vi.fn() }));
vi.mock('@/pages/BuildPage/bench/ModelManagement', () => ({ ModelManagement: () => null }));
beforeEach(() => {
  mock.load.mockReset(); mock.handle.mockReset();
  mock.handle.mockImplementation((value: unknown) => value instanceof Promise ? value.catch(() => undefined) : value);
});
afterEach(cleanup);

it('retains the actual failure without caching an empty successful configuration', async () => {
  const error = normalizeApiError({ status_code: 25001 }, { message: 'config failed' });
  mock.load.mockRejectedValue(error);
  const client = createPlatformQueryClient();
  const { result } = renderHook(() => useLinsightConfig(), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  await waitFor(() => expect(result.current.isError).toBe(true));
  expect(result.current.error).toBe(error);
  expect(result.current.isSuccess).toBe(false);
  expect(client.getQueryData(['linsightModelEnvelope'])).toBeUndefined();
  expect(mock.load).toHaveBeenCalledTimes(1);
  client.clear();
});

it('preserves inherited configuration metadata from a successful query', async () => {
  mock.load.mockResolvedValue({ data: { models: [{ id: 9 }] }, inherited_from_root: true, fallback_blocked: true });
  const client = createPlatformQueryClient();
  const { result } = renderHook(() => useLinsightConfig(), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  await waitFor(() => expect(result.current.data).toMatchObject({ models: [{ id: 9 }], inherited_from_root: true, fallback_blocked: true }));
  client.clear();
});
