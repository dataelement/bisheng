import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { getUserInfo } from '@/controllers/API/user';
import { useCurrentIdentityRefresh } from './useCurrentIdentityRefresh';

vi.mock('@/controllers/API/user', () => ({ getUserInfo: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); focusManager.setFocused(undefined); });

it('reads the current nickname on focus', async () => {
    const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const refreshed = vi.fn();
    const identity = { user_id: 7, user_name: 'OldName', external_id: 'Case01' };
    vi.mocked(getUserInfo).mockResolvedValue({ ...identity, user_name: 'NewName' } as Awaited<ReturnType<typeof getUserInfo>>);
    renderHook(() => useCurrentIdentityRefresh(identity, refreshed), {
        wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider>,
    });
    expect(getUserInfo).not.toHaveBeenCalled();
    act(() => { focusManager.setFocused(false); focusManager.setFocused(true); });
    await waitFor(() => expect(refreshed).toHaveBeenCalledWith({ ...identity, user_name: 'NewName' }));
    expect(getUserInfo).toHaveBeenCalledTimes(1);
    cache.clear();
});

it('rejects a response belonging to a different signed-in identity', async () => {
    const cache = new QueryClient({ logger: { log: vi.fn(), warn: console.warn, error: vi.fn() } });
    const refreshed = vi.fn();
    const identity = { user_id: 7, user_name: 'OldName', external_id: 'Case01' };
    vi.mocked(getUserInfo).mockResolvedValue({ ...identity, user_id: 8 } as Awaited<ReturnType<typeof getUserInfo>>);
    renderHook(() => useCurrentIdentityRefresh(identity, refreshed), {
        wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider>,
    });
    act(() => { focusManager.setFocused(false); focusManager.setFocused(true); });
    await waitFor(() => expect(cache.getQueryState(['current-user-identity', 7])?.status).toBe('error'));
    expect(refreshed).not.toHaveBeenCalled();
    cache.clear();
});

it('does not request an anonymous identity', async () => {
    const cache = new QueryClient();
    renderHook(() => useCurrentIdentityRefresh(undefined, vi.fn()), {
        wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider>,
    });
    act(() => { focusManager.setFocused(false); focusManager.setFocused(true); });
    await act(async () => Promise.resolve());
    expect(getUserInfo).not.toHaveBeenCalled();
    cache.clear();
});
