import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';
import { type PropsWithChildren } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DSH_BROWSER_CONFIG_QUERY_KEY, notifyDshBrowserConfigChanged, subscribeDshBrowserConfigChanges } from '@bisheng/api-client';
import { getDshBrowserConfig } from '@/controllers/API/dshSettings';
import { useDshBrowserConfig } from './useDshBrowserConfig';
import { createPlatformQueryClient } from '@/queryClient';

vi.mock('@/controllers/API/dshSettings', () => ({ getDshBrowserConfig: vi.fn() }));
let client: QueryClient;
let stop: () => void;
function wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
    client = createPlatformQueryClient();
    stop = subscribeDshBrowserConfigChanges(() => {
        void client.invalidateQueries({ queryKey: DSH_BROWSER_CONFIG_QUERY_KEY });
    });
    vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: true, download_url: null, launch_url: 'dsh-desktop://login' });
});
afterEach(() => { cleanup(); stop(); client.clear(); focusManager.setFocused(undefined); vi.clearAllMocks(); vi.useRealTimers(); });

it('deduplicates concurrent consumers and reuses fresh data after remount', async () => {
    const first = renderHook(() => [useDshBrowserConfig(), useDshBrowserConfig()], { wrapper });
    const second = renderHook(() => useDshBrowserConfig(), { wrapper });
    await waitFor(() => expect(first.result.current.every(value => value.config?.enabled)).toBe(true));
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
    first.unmount(); second.unmount();
    const remounted = renderHook(() => useDshBrowserConfig(), { wrapper });
    expect(remounted.result.current.config?.enabled).toBe(true);
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
});

it('does not poll or refetch on focus while fresh; refreshes once when stale', async () => {
    const view = renderHook(() => [useDshBrowserConfig(), useDshBrowserConfig()], { wrapper });
    await waitFor(() => expect(view.result.current[0].config).not.toBeNull());
    vi.useFakeTimers();
    await act(async () => {
        vi.advanceTimersByTime(90000);
        focusManager.setFocused(false); focusManager.setFocused(true);
    });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
    await act(async () => {
        vi.advanceTimersByTime(5 * 60 * 1000);
    });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
    await act(async () => { focusManager.setFocused(false); focusManager.setFocused(true); });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(2);
});

it.each(['same tab', 'other tab'])('refreshes all subscribers once after a settings save in %s', async (source) => {
    const view = renderHook(() => [useDshBrowserConfig(), useDshBrowserConfig()], { wrapper });
    await waitFor(() => expect(view.result.current[0].config).not.toBeNull());
    vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: true, download_url: 'http://downloads.test/new', launch_url: 'bisheng://login' });
    act(() => {
        if (source === 'same tab') notifyDshBrowserConfigChanged();
        else window.dispatchEvent(new StorageEvent('storage', { key: 'dsh-browser-config-changed', newValue: 'revision' }));
    });
    await waitFor(() => expect(view.result.current.every(value => value.config?.download_url === 'http://downloads.test/new')).toBe(true));
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(2);
});

it('does not retry failed requests on timers or new consumers', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(getDshBrowserConfig).mockRejectedValue(new Error('unavailable'));
    const view = renderHook(() => useDshBrowserConfig(), { wrapper });
    await waitFor(() => expect(view.result.current.failed).toBe(true));
    vi.useFakeTimers();
    await act(async () => { vi.advanceTimersByTime(90000); });
    renderHook(() => useDshBrowserConfig(), { wrapper });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
});

it('keeps the last shared configuration if a background refresh fails', async () => {
    const view = renderHook(() => useDshBrowserConfig(), { wrapper });
    await waitFor(() => expect(view.result.current.config?.enabled).toBe(true));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(getDshBrowserConfig).mockRejectedValue(new Error('offline'));
    act(() => notifyDshBrowserConfigChanged());
    await waitFor(() => expect(client.getQueryState(DSH_BROWSER_CONFIG_QUERY_KEY)?.status).toBe('error'));
    expect(view.result.current.config?.enabled).toBe(true);
    expect(view.result.current.failed).toBe(false);
});
