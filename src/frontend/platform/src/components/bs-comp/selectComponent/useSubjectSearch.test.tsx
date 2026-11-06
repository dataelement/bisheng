import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useSubjectSearch } from './useSubjectSearch';

afterEach(cleanup);

it('keeps loaded rows mounted while the next page is loading', async () => {
    let finish: (page: { data: string[]; total: number }) => void = () => {};
    const fetchPage = vi.fn().mockResolvedValueOnce({ data: ['Alice'], total: 2 })
        .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const { result } = renderHook(() => useSubjectSearch({ fetchPage, delay: 0, retainRowsOnAppend: true }));
    await waitFor(() => expect(result.current.rows).toEqual(['Alice']));
    act(() => result.current.loadMore());
    expect(result.current.loading).toBe(false);
    expect(result.current.loadingMore).toBe(true);
    expect(result.current.rows).toEqual(['Alice']);
    await act(async () => finish({ data: ['Bob'], total: 2 }));
    expect(result.current.rows).toEqual(['Alice', 'Bob']);
});

it('retains rows after a failed next page and retries the same page', async () => {
    const fetchPage = vi.fn().mockResolvedValueOnce({ data: ['Alice'], total: 2 })
        .mockRejectedValueOnce(new Error('Offline'))
        .mockResolvedValueOnce({ data: ['Bob'], total: 2 });
    const { result } = renderHook(() => useSubjectSearch({ fetchPage, delay: 0, retainRowsOnAppend: true }));
    await waitFor(() => expect(result.current.rows).toEqual(['Alice']));
    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.loadMoreFailed).toBe(true));
    expect(result.current.failed).toBe(false);
    expect(result.current.rows).toEqual(['Alice']);
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.rows).toEqual(['Alice', 'Bob']));
    expect(fetchPage.mock.calls.map(call => call[1])).toEqual([1, 2, 2]);
});
