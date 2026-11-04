import { cleanup, renderHook, waitFor } from '@testing-library/react';
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
