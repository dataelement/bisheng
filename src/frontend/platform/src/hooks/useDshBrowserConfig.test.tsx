import { act, cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { getDshBrowserConfig } from '@/controllers/API/dshSettings';
import { useDshBrowserConfig } from './useDshBrowserConfig';

vi.mock('@/controllers/API/dshSettings', () => ({ getDshBrowserConfig: vi.fn() }));
beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: true, download_url: null, launch_url: 'dsh-desktop://login' });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); });

it('refreshes browser settings on the documented 30-second interval, focus and settings change', async () => {
    renderHook(() => useDshBrowserConfig());
    await act(async () => {});
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(29999); });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(2);
    await act(async () => { window.dispatchEvent(new Event('focus')); });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(3);
    await act(async () => { window.dispatchEvent(new Event('dsh-settings-changed')); });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(4);
});

it('creates one polling subscription per consumer but does not refetch for an ordinary button rerender', async () => {
    function Consumers() {
        useDshBrowserConfig(); useDshBrowserConfig();
        const [count, setCount] = useState(0);
        return <button onClick={() => setCount(count + 1)}>count-{count}</button>;
    }
    render(<Consumers />);
    await act(async () => {});
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: 'count-0' }));
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(2);
    await act(async () => { vi.advanceTimersByTime(30000); });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(4);
});

it('cancels the active request and stops polling after unmount', async () => {
    const view = renderHook(() => useDshBrowserConfig());
    await act(async () => {});
    const signal = vi.mocked(getDshBrowserConfig).mock.calls[0][0];
    view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => { vi.advanceTimersByTime(90000); window.dispatchEvent(new Event('focus')); });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
});

it('stops polling when DSH is not deployed', async () => {
    vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: false, enabled: false, download_url: null, launch_url: 'dsh-desktop://login' });
    const { result } = renderHook(() => useDshBrowserConfig());
    await act(async () => {});
    expect(result.current.config?.management_enabled).toBe(false);
    await act(async () => { vi.advanceTimersByTime(90000); window.dispatchEvent(new Event('focus')); });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(1);
});

it('keeps polling the runtime toggle when DSH is deployed but switched off', async () => {
    vi.mocked(getDshBrowserConfig).mockResolvedValue({ management_enabled: true, enabled: false, download_url: null, launch_url: 'dsh-desktop://login' });
    renderHook(() => useDshBrowserConfig());
    await act(async () => {});
    await act(async () => { vi.advanceTimersByTime(30000); });
    expect(getDshBrowserConfig).toHaveBeenCalledTimes(2);
});
