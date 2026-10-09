import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { getKnowledgeInfo } from '~/api/linsight';
import { useGetOrgToolPages } from './queries';

jest.mock('~/api/linsight', () => ({ getKnowledgeInfo: jest.fn() }));

it('loads the next organization knowledge page with the returned cursor', async () => {
  const getPage = jest.mocked(getKnowledgeInfo);
  getPage.mockImplementation(async ({ cursor }) => ({
    data: cursor
      ? { data: [{ id: 22, name: 'Second' }], page_size: 1, has_more: false, next_cursor: null }
      : { data: [{ id: 11, name: 'First' }], page_size: 1, has_more: true, next_cursor: 'next-page' },
  }));

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(
    () => useGetOrgToolPages({ page_size: 1, sort_by: 'name', action: 'visible' }),
    { wrapper },
  );

  await waitFor(() => expect(result.current.data?.pages[0].data.map((item) => item.id)).toEqual([11]));
  expect(result.current.hasNextPage).toBe(true);

  await act(async () => {
    await result.current.fetchNextPage();
  });

  await waitFor(() => expect(result.current.data?.pages.map((page) => page.data.map((item) => item.id))).toEqual([[11], [22]]));
  expect(result.current.hasNextPage).toBe(false);
  expect(getPage).toHaveBeenNthCalledWith(2, expect.objectContaining({ cursor: 'next-page' }));
});
