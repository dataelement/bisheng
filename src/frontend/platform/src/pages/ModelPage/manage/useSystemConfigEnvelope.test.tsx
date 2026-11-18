import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useSystemConfigEnvelope } from './useSystemConfigEnvelope';
const notify = vi.hoisted(() => vi.fn());
vi.mock('@/controllers/request', () => ({ showApiError: notify }));
afterEach(() => { cleanup(); notify.mockClear(); });
it('restores loading and exposes failure without accepting an empty configuration', async () => {
    const error = new Error('offline');
    const fetcher = vi.fn().mockRejectedValue(error);
    const { result } = renderHook(() => useSystemConfigEnvelope(fetcher));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.config).toBeNull();
    expect(result.current.error).toBe(error);
    expect(notify).toHaveBeenCalledWith(error);
});
it('retains successful inherited configuration metadata', async () => {
    const fetcher = vi.fn().mockResolvedValue({ data: { model_id: 9 }, inherited_from_root: true, fallback_blocked: true });
    const { result } = renderHook(() => useSystemConfigEnvelope(fetcher));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current).toMatchObject({ config: { model_id: 9 }, inheritedFromRoot: true, fallbackBlocked: true, error: null });
});

it('keeps reload stable and refreshes accepted source only after the next GET succeeds', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ data: { model_id: 9 }, inherited_from_root: true })
        .mockResolvedValueOnce({ data: { model_id: 7 }, inherited_from_root: false });
    const { result, rerender } = renderHook(() => useSystemConfigEnvelope(fetcher));
    await waitFor(() => expect(result.current.loading).toBe(false));
    const reload = result.current.reload;
    rerender();
    expect(result.current.reload).toBe(reload);
    await act(async () => { await reload(); });
    expect(result.current).toMatchObject({ config: { model_id: 7 }, inheritedFromRoot: false, error: null });
});
it('a failed reload preserves the prior value and provenance and supports a provenance-only retry', async () => {
    const failure = new Error('refresh unavailable');
    const fetcher = vi.fn().mockResolvedValueOnce({ data: { model_id: 9 }, inherited_from_root: true })
        .mockRejectedValueOnce(failure).mockResolvedValueOnce({ data: { model_id: 7 }, inherited_from_root: false });
    const { result } = renderHook(() => useSystemConfigEnvelope(fetcher));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => { await expect(result.current.reload()).rejects.toBe(failure); });
    expect(result.current).toMatchObject({ config: { model_id: 9 }, inheritedFromRoot: true, error: failure });
    await act(async () => { await result.current.reload({ updateConfig: false }); });
    expect(result.current).toMatchObject({ config: { model_id: 9 }, inheritedFromRoot: false, error: null });
});

it('ignores a late failed GET after the column unmounts', async () => {
    let rejectLoad: (cause: unknown) => void = () => undefined;
    const fetcher = vi.fn(() => new Promise<never>((_resolve, reject) => { rejectLoad = reject; }));
    const { unmount } = renderHook(() => useSystemConfigEnvelope(fetcher));
    unmount();
    await act(async () => { rejectLoad(new Error('old tenant response')); });
    expect(notify).not.toHaveBeenCalled();
});
