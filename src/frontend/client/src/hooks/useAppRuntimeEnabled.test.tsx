/**
 * F054 T071 — the client's read of the app-factory runtime-layer switch.
 *
 * The flag gates whether hosted applications exist in this environment at all,
 * so the only behaviours worth pinning are: it fails closed (loading, request
 * failure, or an older backend that never sends the key all read as "not
 * deployed"), and every consumer shares one `/api/v1/env` fetch.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { getBysConfigApi } from '~/api/apps';
import { useAppRuntimeEnabled } from './useAppRuntimeEnabled';

jest.mock('~/api/apps', () => ({ getBysConfigApi: jest.fn() }));

const mockGetBysConfigApi = getBysConfigApi as jest.Mock;

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe('useAppRuntimeEnabled', () => {
  it('reads the flag out of the /api/v1/env envelope', async () => {
    mockGetBysConfigApi.mockResolvedValue({ data: { app_runtime_enabled: true } });

    const { result } = renderHook(() => useAppRuntimeEnabled(), { wrapper: createWrapper() });

    // Fails closed until the config lands.
    expect(result.current).toBe(false);
    await waitFor(() => expect(result.current).toBe(true));
  });

  it('stays false when the layer is not deployed', async () => {
    mockGetBysConfigApi.mockResolvedValue({ data: { app_runtime_enabled: false } });

    const { result } = renderHook(() => useAppRuntimeEnabled(), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGetBysConfigApi).toHaveBeenCalled());
    expect(result.current).toBe(false);
  });

  it('stays false on a backend that does not send the key', async () => {
    mockGetBysConfigApi.mockResolvedValue({ data: { env: 'prod' } });

    const { result } = renderHook(() => useAppRuntimeEnabled(), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGetBysConfigApi).toHaveBeenCalled());
    expect(result.current).toBe(false);
  });

  it('stays false when the request fails', async () => {
    mockGetBysConfigApi.mockRejectedValue(new Error('offline'));

    const { result } = renderHook(() => useAppRuntimeEnabled(), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGetBysConfigApi).toHaveBeenCalled());
    expect(result.current).toBe(false);
  });

  it('shares one request across every consumer', async () => {
    mockGetBysConfigApi.mockResolvedValue({ data: { app_runtime_enabled: true } });
    const wrapper = createWrapper();

    const first = renderHook(() => useAppRuntimeEnabled(), { wrapper });
    const second = renderHook(() => useAppRuntimeEnabled(), { wrapper });

    await waitFor(() => expect(first.result.current).toBe(true));
    await waitFor(() => expect(second.result.current).toBe(true));
    expect(mockGetBysConfigApi).toHaveBeenCalledTimes(1);
  });
});
