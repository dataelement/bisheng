import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useSpaceActions } from './useSpaceActions';
import { SpaceSortType, unsubscribeSpaceApi } from '~/api/knowledge';

const mockToast = jest.fn();
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockToast }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('./useKnowledgeDeletion', () => ({ useKnowledgeDeletion: () => ({ open: jest.fn() }) }));
jest.mock('~/api/knowledge', () => ({ SpaceSortType: { UPDATE_TIME: 'update_time' }, unsubscribeSpaceApi: jest.fn() }));

it.each(['success', 'organization-denied', 'failure'])('refreshes only the affected eligibility after %s', async (outcome) => {
  const read = jest.mocked(unsubscribeSpaceApi);
  if (outcome === 'success') read.mockResolvedValueOnce({ status_code: 200 });
  else read.mockRejectedValueOnce({ status_code: outcome === 'organization-denied' ? 18080 : 500 });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const affected = ['space-exit-status', '7', '42', 0, '3'];
  const unrelated = ['space-exit-status', '7', '42', 0, '4'];
  client.setQueryData(affected, { can_exit: true, reason: null });
  client.setQueryData(unrelated, { can_exit: true, reason: null });
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  const { result } = renderHook(() => useSpaceActions({
    createdSortBy: SpaceSortType.UPDATE_TIME,
    joinedSortBy: SpaceSortType.UPDATE_TIME,
    departmentSortBy: SpaceSortType.UPDATE_TIME,
    createdSpaces: [], joinedSpaces: [], departmentSpaces: [],
    onSpaceSelect: jest.fn(), onActiveSpaceUpdate: jest.fn(),
  }), { wrapper });
  await act(async () => { await result.current.handleLeaveSpace('3'); });
  expect(client.getQueryState(affected)?.isInvalidated).toBe(true);
  expect(client.getQueryState(unrelated)?.isInvalidated).toBe(false);
});

it('removes an exited personal space from department and joined list caches', async () => {
  jest.mocked(unsubscribeSpaceApi).mockResolvedValueOnce({ status_code: 200 });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const row = { id: '3' };
  const other = { id: '4' };
  const joined = ['knowledgeSpaces', 'joined', SpaceSortType.UPDATE_TIME];
  const department = ['knowledgeSpaces', 'department', SpaceSortType.UPDATE_TIME];
  client.setQueryData(joined, [row, other]);
  client.setQueryData(department, [row, other]);
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  const { result } = renderHook(() => useSpaceActions({
    createdSortBy: SpaceSortType.UPDATE_TIME,
    joinedSortBy: SpaceSortType.UPDATE_TIME,
    departmentSortBy: SpaceSortType.UPDATE_TIME,
    createdSpaces: [], joinedSpaces: [], departmentSpaces: [],
    onSpaceSelect: jest.fn(), onActiveSpaceUpdate: jest.fn(),
  }), { wrapper });
  await act(async () => { await result.current.handleLeaveSpace('3'); });
  expect(client.getQueryData(joined)).toEqual([other]);
  expect(client.getQueryData(department)).toEqual([other]);
  expect(client.getQueryState(department)?.isInvalidated).toBe(true);
});
