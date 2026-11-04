import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CHANNEL_STATE_REFRESH_MS, refreshChannelState, useChannelAccessGuard, useChannelStateRefresh } from './useChannelStateRefresh';

jest.mock('~/api/channels', () => ({ getChannelDetailApi: jest.fn() }));
import { getChannelDetailApi } from '~/api/channels';

let mockActivate: () => void;
let mockDeactivate: () => void;
jest.mock('react-activation', () => ({
    useActivate: (callback: () => void) => { mockActivate = callback; },
    useUnactivate: (callback: () => void) => { mockDeactivate = callback; },
}));

beforeEach(() => { jest.useFakeTimers(); });
afterEach(() => { jest.useRealTimers(); });

it('refreshes on focus, visibility and interval with the latest callback', () => {
    const first = jest.fn();
    const latest = jest.fn();
    const { rerender, unmount } = renderHook(({ refresh }) => useChannelStateRefresh(refresh), { initialProps: { refresh: first } });
    rerender({ refresh: latest });
    act(() => { window.dispatchEvent(new Event('focus')); });
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    act(() => { jest.advanceTimersByTime(CHANNEL_STATE_REFRESH_MS); });
    expect(latest).toHaveBeenCalledTimes(3);
    expect(first).toHaveBeenCalledTimes(0);
    unmount();
    act(() => { jest.advanceTimersByTime(CHANNEL_STATE_REFRESH_MS); window.dispatchEvent(new Event('focus')); });
    expect(latest).toHaveBeenCalledTimes(3);
});

it('pauses a cached or hidden surface and refreshes on activation', () => {
    const refresh = jest.fn();
    renderHook(() => useChannelStateRefresh(refresh));
    act(() => { mockDeactivate(); });
    act(() => { jest.advanceTimersByTime(CHANNEL_STATE_REFRESH_MS); window.dispatchEvent(new Event('focus')); });
    expect(refresh).toHaveBeenCalledTimes(0);
    act(() => { mockActivate(); });
    expect(refresh).toHaveBeenCalledTimes(1);
    const visibility = jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    act(() => { jest.advanceTimersByTime(CHANNEL_STATE_REFRESH_MS); });
    expect(refresh).toHaveBeenCalledTimes(1);
    visibility.mockRestore();
});

it('keeps disabled surfaces idle', () => {
    const refresh = jest.fn();
    renderHook(() => useChannelStateRefresh(refresh, false));
    act(() => { mockActivate(); window.dispatchEvent(new Event('focus')); jest.advanceTimersByTime(CHANNEL_STATE_REFRESH_MS); });
    expect(refresh).toHaveBeenCalledTimes(0);
});

it('invalidates the channel state family while preserving other resources', async () => {
    const client = new QueryClient();
    const keys = [['channels', 'subscribed'], ['channelDetail', 'c1'], ['channelPreviewDetail', 'c1'], ['channelRecommend'], ['knowledge', 'k1']];
    keys.forEach((key) => client.setQueryData(key, {}));
    await refreshChannelState(client);
    expect(keys.map((key) => client.getQueryState(key)?.isInvalidated)).toEqual([true, true, true, true, false]);
    client.clear();
});

it('closes opened content when a fresh permission response revokes access', async () => {
    jest.useRealTimers();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const revoked = jest.fn();
    jest.mocked(getChannelDetailApi).mockResolvedValue({ actions: ['visible'] } as never);
    const wrapper = ({ children }: React.PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { unmount } = renderHook(() => useChannelAccessGuard('c1', revoked), { wrapper });
    await waitFor(() => expect(client.getQueryData(['channelDetail', 'c1'])).toEqual({ actions: ['visible'] }));
    expect(revoked).toHaveBeenCalledTimes(0);
    jest.mocked(getChannelDetailApi).mockResolvedValue({ actions: [] } as never);
    await act(async () => { await refreshChannelState(client); });
    await waitFor(() => expect(revoked).toHaveBeenCalledTimes(1));
    unmount(); client.clear();
});
