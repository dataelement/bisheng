import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
// eslint-disable-next-line no-restricted-imports -- Exercise the existing sidebar atoms with their real provider.
import { RecoilRoot } from 'recoil';
import { normalizeApiError } from '@bisheng/api-client';
import { getAppConversationsApi } from '~/api/apps';
import { useAppSidebar } from './useAppSidebar';
import { useStandaloneSidebar } from '~/pages/standaloneChat/hooks/useStandaloneSidebar';
import { appConversationsState } from '~/pages/appChat/store/appSidebarAtoms';
const mockNavigate = jest.fn();
const mockParams = { fid: 'flow', type: '5', conversationId: 'draft' };
const localize = (key: string) => key;
jest.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate, useLocation: () => ({ state: null }), useParams: () => mockParams }));
jest.mock('~/hooks', () => ({ useLocalize: () => localize }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/utils', () => ({ generateUUID: () => 'draft', copyText: jest.fn() }));
jest.mock('~/pages/apps/appUtils', () => ({ groupConversationsByTime: () => [], getAppShareUrl: () => '' }));
jest.mock('~/pages/appChat/useWebsocket', () => ({ closeAppChatWebSocket: jest.fn() }));
jest.mock('~/api/apps', () => ({ getAppConversationsApi: jest.fn(), getAssistantDetailApi: jest.fn(async () => ({ status_code: 200, data: {} })), getFlowApi: jest.fn() }));
const error = normalizeApiError({ status_code: 19004, data: { reason: 'unavailable' } }, { message: 'list failed' });
const old = { id: 'old', title: 'Existing chat', flowId: 'flow', flowType: 5, createdAt: '', updatedAt: '' };
const wrapper = ({ children }: { children: React.ReactNode }) => <RecoilRoot initializeState={({ set }) => set(appConversationsState, [old])}>{children}</RecoilRoot>;
beforeEach(() => { (getAppConversationsApi as jest.Mock).mockReset(); mockNavigate.mockReset(); mockParams.conversationId = 'draft'; });
it('app history retains the full rejection and old list without creating a false successful draft', async () => {
  (getAppConversationsApi as jest.Mock).mockRejectedValue(error);
  const { result } = renderHook(useAppSidebar, { wrapper });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.listError).toBe(error);
  expect(result.current.conversations).toEqual([old]);
  await act(async () => { await expect(result.current.fetchConversations()).rejects.toBe(error); });
  (getAppConversationsApi as jest.Mock).mockResolvedValue({ data: { list: [] } });
  await act(async () => { await result.current.retryConversations(); });
  expect(result.current.listError).toBeNull();
  expect(result.current.conversations.map(c => c.id)).toEqual(['draft']);
});
it('standalone history stays unloaded on failure, then selects the fetched history only after retry succeeds', async () => {
  (getAppConversationsApi as jest.Mock).mockRejectedValue(error);
  const { result } = renderHook(() => useStandaloneSidebar({ mode: 'auth', flowType: 'assistant', flowId: 'flow', apiVersion: 'v1', autoRerunOnOpen: false }), { wrapper });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.listError).toBe(error);
  expect(result.current.historyLoaded).toBe(false);
  expect(result.current.activeChatId).toBe('');
  await act(async () => { await expect(result.current.fetchConversations()).rejects.toBe(error); });
  (getAppConversationsApi as jest.Mock).mockResolvedValue({ data: { list: [{ chat_id: 'server', name: 'Server chat' }] } });
  await act(async () => { await result.current.retryConversations(); });
  expect(result.current.historyLoaded).toBe(true);
  expect(result.current.activeChatId).toBe('server');
  expect(result.current.listError).toBeNull();
  act(() => result.current.createNewChat());
  await act(async () => { await result.current.fetchConversations(); });
  expect(result.current.conversations.map(c => c.id)).toEqual(['draft', 'server']);
});

it('preserves local guest history and draft merging without a server conversation request', async () => {
  localStorage.setItem('bs_standalone_convos_guest-flow', JSON.stringify([{ id: 'local', title: 'Local chat', createdAt: '', updatedAt: '' }]));
  const { result } = renderHook(() => useStandaloneSidebar({ mode: 'guest', flowType: 'assistant', flowId: 'guest-flow', apiVersion: 'v3', autoRerunOnOpen: false }), { wrapper });
  await waitFor(() => expect(result.current.historyLoaded).toBe(true));
  expect(result.current.activeChatId).toBe('local');
  expect(result.current.listError).toBeNull();
  act(() => result.current.createNewChat());
  await act(async () => { await result.current.fetchConversations(); });
  expect(result.current.conversations.map(c => c.id)).toEqual(['draft', 'local']);
  expect(getAppConversationsApi).not.toHaveBeenCalled();
});

it('retries with the current conversation after failed initialization and a new chat navigation', async () => {
  mockParams.conversationId = 'failed-a';
  (getAppConversationsApi as jest.Mock).mockRejectedValue(error);
  const { result, rerender } = renderHook(useAppSidebar, { wrapper });
  await waitFor(() => expect(result.current.listError).toBe(error));
  act(() => result.current.createNewChat());
  mockParams.conversationId = 'draft';
  rerender();
  (getAppConversationsApi as jest.Mock).mockResolvedValue({ data: { list: [] } });
  await act(async () => { await result.current.retryConversations(); });
  expect(result.current.conversations.map(c => c.id)).toEqual(['draft']);
  expect(result.current.listError).toBeNull();
});
