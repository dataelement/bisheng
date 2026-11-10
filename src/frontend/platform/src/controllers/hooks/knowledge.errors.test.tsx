import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { getKnowledgeDetailApi } from '../API';
import { useKnowledgeDetails } from './knowledge';

vi.mock('../API', () => ({ getKnowledgeDetailApi: vi.fn() }));
afterEach(cleanup);

it('exposes the complete initial failure and clears it only after a successful retry', async () => {
    const error = new Error('Initial failure');
    vi.mocked(getKnowledgeDetailApi).mockRejectedValueOnce(error);
    const { result } = renderHook(() => useKnowledgeDetails(['1']));
    await waitFor(() => expect(result.current[2]).toBe(error));
    vi.mocked(getKnowledgeDetailApi).mockResolvedValueOnce([{ id: 1, name: 'Knowledge' }]);
    await act(() => result.current[1](['1']));
    expect(result.current[2]).toBe(null);
    expect(result.current[0]).toEqual([{ id: 1, name: 'Knowledge' }]);
});

it('rejects manual detail refresh with the original error and preserves the last successful details', async () => {
    const details = [{ id: 1, name: 'Knowledge' }];
    vi.mocked(getKnowledgeDetailApi).mockResolvedValueOnce(details);
    const { result } = renderHook(() => useKnowledgeDetails(['1']));
    await waitFor(() => expect(result.current[0]).toEqual(details));
    const error = new Error('Knowledge unavailable');
    vi.mocked(getKnowledgeDetailApi).mockRejectedValueOnce(error);
    await act(async () => {
        await expect(result.current[1](['1'])).rejects.toBe(error);
    });
    expect(result.current[0]).toEqual(details);
});
