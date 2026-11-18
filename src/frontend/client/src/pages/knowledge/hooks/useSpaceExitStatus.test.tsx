import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useSpaceExitStatus } from './useSpaceExitStatus';
import request, { prepareBrowserHeaders } from '~/api/request';
import type { SpaceExitStatus } from '~/api/knowledgeSpaceExit';
import type { ReactNode } from 'react';

let mockUserId = '7';
jest.mock('~/hooks', () => ({ useAuthContext: () => ({ user: { id: mockUserId } }) }));
jest.mock('~/api/request', () => ({
  __esModule: true,
  default: { get: jest.fn() },
  prepareBrowserHeaders: jest.fn(),
}));
const read = jest.mocked(request.get);
const exitStatusResponse = (data: SpaceExitStatus) => ({
  status_code: 200,
  status_message: 'SUCCESS',
  data,
});
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  mockUserId = '7';
  jest.mocked(prepareBrowserHeaders).mockResolvedValue({ 'X-Management-Tenant': '42' });
  read.mockReset();
  jest.mocked(prepareBrowserHeaders).mockClear();
});
it('requests lazily and allows a personal grant only after the authoritative result', async () => {
  read.mockResolvedValue(exitStatusResponse({ can_exit: true, reason: null }));
  const { result } = renderHook(() => useSpaceExitStatus('3', false), { wrapper });
  expect(result.current.canExit).toBe(false);
  expect(read).not.toHaveBeenCalled();
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.canExit).toBe(true));
  expect(read).toHaveBeenCalledWith('/api/v1/knowledge/space/3/exit-status');
});
it.each(['creator', 'organization_grant', 'no_personal_grant'] as const)('denies %s in active detail queries', async (reason) => {
  read.mockResolvedValue(exitStatusResponse({ can_exit: false, reason }));
  const { result } = renderHook(() => useSpaceExitStatus('3'), { wrapper });
  await waitFor(() => expect(read).toHaveBeenCalled());
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.canExit).toBe(false);
});
it('removes an old allow while refreshing, on failure, and permits a later retry', async () => {
  read.mockResolvedValueOnce(exitStatusResponse({ can_exit: true, reason: null }));
  const { result } = renderHook(() => useSpaceExitStatus('3'), { wrapper });
  await waitFor(() => expect(result.current.canExit).toBe(true));
  read.mockRejectedValueOnce(new Error('offline'));
  await act(async () => { await result.current.refresh(); });
  expect(result.current.canExit).toBe(false);
  read.mockResolvedValueOnce(exitStatusResponse({ can_exit: true, reason: null }));
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.canExit).toBe(true));
});
it('does not retain an allow when the identity or tenant scope changes', async () => {
  read.mockResolvedValue(exitStatusResponse({ can_exit: true, reason: null }));
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
  read.mockResolvedValue(exitStatusResponse({ can_exit: true, reason: null }));
  const { result } = renderHook(() => useSpaceExitStatus('3', false), { wrapper });
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.canExit).toBe(true));
  expect(read).toHaveBeenCalledTimes(1);
  await act(async () => { await result.current.refresh(); });
  await waitFor(() => expect(result.current.canExit).toBe(true));
  expect(read).toHaveBeenCalledTimes(2);
  expect(prepareBrowserHeaders).toHaveBeenCalledTimes(1);
});
