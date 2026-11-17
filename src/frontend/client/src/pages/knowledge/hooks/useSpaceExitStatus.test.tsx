import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useSpaceExitStatus } from './useSpaceExitStatus';
import { getSpaceExitStatus, resolveSpaceExitScope } from '~/api/knowledgeSpaceExit';
import type { ReactNode } from 'react';

let mockUserId = '7';
jest.mock('~/hooks', () => ({ useAuthContext: () => ({ user: { id: mockUserId } }) }));
jest.mock('~/api/knowledgeSpaceExit', () => ({ getSpaceExitStatus: jest.fn(), resolveSpaceExitScope: jest.fn() }));
const read = jest.mocked(getSpaceExitStatus);
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  mockUserId = '7';
  jest.mocked(resolveSpaceExitScope).mockResolvedValue('42');
  read.mockReset();
  jest.mocked(resolveSpaceExitScope).mockClear();
});
it('requests lazily and allows a personal grant only after the authoritative result', async () => {
  read.mockResolvedValue({ can_exit: true, reason: null });
  const { result } = renderHook(() => useSpaceExitStatus('3', false), { wrapper });
  expect(result.current.canExit).toBe(false);
  expect(read).not.toHaveBeenCalled();
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.canExit).toBe(true));
  expect(read).toHaveBeenCalledWith('3');
});
it.each(['creator', 'organization_grant', 'no_personal_grant'] as const)('denies %s in active detail queries', async (reason) => {
  read.mockResolvedValue({ can_exit: false, reason });
  const { result } = renderHook(() => useSpaceExitStatus('3'), { wrapper });
  await waitFor(() => expect(read).toHaveBeenCalled());
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.canExit).toBe(false);
});
it('removes an old allow while refreshing, on failure, and permits a later retry', async () => {
  read.mockResolvedValueOnce({ can_exit: true, reason: null });
  const { result } = renderHook(() => useSpaceExitStatus('3'), { wrapper });
  await waitFor(() => expect(result.current.canExit).toBe(true));
  read.mockRejectedValueOnce(new Error('offline'));
  await act(async () => { await result.current.refresh(); });
  expect(result.current.canExit).toBe(false);
  read.mockResolvedValueOnce({ can_exit: true, reason: null });
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.canExit).toBe(true));
});
it('does not retain an allow when the identity or tenant scope changes', async () => {
  read.mockResolvedValue({ can_exit: true, reason: null });
  const { result, rerender } = renderHook(() => useSpaceExitStatus('3', false), { wrapper });
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.canExit).toBe(true));
  mockUserId = '8';
  rerender();
  expect(result.current.canExit).toBe(false);
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.canExit).toBe(true));
  act(() => { window.dispatchEvent(new Event('bisheng:management-scope-changed')); });
  expect(result.current.canExit).toBe(false);
});

it('makes one status request per menu refresh without refetching an established scope', async () => {
  read.mockResolvedValue({ can_exit: true, reason: null });
  const { result } = renderHook(() => useSpaceExitStatus('3', false), { wrapper });
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.canExit).toBe(true));
  expect(read).toHaveBeenCalledTimes(1);
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.canExit).toBe(true));
  expect(read).toHaveBeenCalledTimes(2);
  expect(resolveSpaceExitScope).toHaveBeenCalledTimes(1);
});
