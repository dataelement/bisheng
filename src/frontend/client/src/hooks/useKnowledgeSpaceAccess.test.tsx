import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';
import { checkResourceAction } from '~/api/permission';
import { useKnowledgeSpaceAccess } from './useKnowledgeSpaceAccess';
import { useConversationKnowledge } from './useConversationKnowledge';

let mockUser = 'sara6';
jest.mock('./AuthContext', () => ({ useAuthContext: () => ({ user: { id: mockUser } }) }));
jest.mock('./useLocalize', () => ({ __esModule: true,
  default: () => (key: string, args?: { names: string }) => `${key}${args?.names ? `: ${args.names}` : ''}`,
}));
jest.mock('~/api/permission', () => ({ checkResourceAction: jest.fn() }));
const space = { id: '14', name: 'Approval space', type: 'space' as const };
const other = { id: '15', name: 'Department space', type: 'space' as const };
const org = { id: '11', name: 'Organization', type: 'org' as const };
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, wrapper };
}
beforeEach(() => {
  mockUser = 'sara6'; localStorage.clear();
  jest.mocked(checkResourceAction).mockReset().mockResolvedValue({ allowed: true });
  focusManager.setFocused(true);
});
afterEach(() => focusManager.setFocused(undefined));

test('restored revoked selection is excluded and the reason survives reload until reselection', async () => {
  localStorage.setItem('bs-conversation:sara6:knowledge:old', JSON.stringify([space]));
  jest.mocked(checkResourceAction).mockResolvedValue({ allowed: false });
  const useChatScope = () => {
    const saved = useConversationKnowledge(mockUser, 'old');
    return { ...saved, ...useKnowledgeSpaceAccess(saved.selectedOrgKbs, 'old') };
  };
  const first = renderHook(useChatScope, setup());
  expect(first.result.current.blocked).toBe(true);
  await waitFor(() => expect(first.result.current.message).toContain('knowledgeAccess.revoked'));
  expect(first.result.current.available).toEqual([]);
  expect(first.result.current.message).toContain(space.name);
  first.unmount();
  const second = renderHook(useChatScope, setup());
  await waitFor(() => expect(second.result.current.message).toContain('knowledgeAccess.revoked'));
  act(() => second.result.current.setSelectedOrgKbs([]));
  expect(second.result.current.available).toEqual([]);
  expect(second.result.current.blocked).toBe(false);
  expect(second.result.current.message).toBe('');
});

test('uses authoritative permission for department/direct grants and preserves organization selection', async () => {
  jest.mocked(checkResourceAction).mockImplementation(async ({ resource_id }) => ({ allowed: resource_id === '15' }));
  const { result } = renderHook(() => useKnowledgeSpaceAccess([space, other, org], 'mixed'), setup());
  await waitFor(() => expect(result.current.message).toContain('knowledgeAccess.revoked'));
  expect(result.current.available).toEqual([other, org]);
  expect(checkResourceAction).toHaveBeenCalledWith(
    { resource_type: 'knowledge_space', resource_id: '15', action: 'visible' }, expect.anything());
});

test('focus revalidates a previously accessible selection after another tab leaves', async () => {
  const { result } = renderHook(() => useKnowledgeSpaceAccess([space], 'old'), setup());
  await waitFor(() => expect(result.current.blocked).toBe(false));
  jest.mocked(checkResourceAction).mockResolvedValue({ allowed: false });
  act(() => { focusManager.setFocused(false); focusManager.setFocused(true); });
  await waitFor(() => expect(result.current.message).toContain('knowledgeAccess.revoked'));
  expect(result.current.available).toEqual([]);
});

test('request failures keep intent, block sends, and recover without declaring revocation', async () => {
  jest.mocked(checkResourceAction).mockRejectedValue(new Error('offline'));
  const { result } = renderHook(() => useKnowledgeSpaceAccess([space], 'old'), setup());
  await waitFor(() => expect(result.current.failed).toBe(true));
  expect(result.current.available).toEqual([space]);
  expect(result.current.message).toBe('knowledgeAccess.failed');
  expect(result.current.blocked).toBe(true);
  jest.mocked(checkResourceAction).mockResolvedValue({ allowed: true });
  await act(async () => { await result.current.retry(); });
  await waitFor(() => expect(result.current.blocked).toBe(false));
});

test('late permission replies stay with their account and conversation', async () => {
  let resolveOld: (value: { allowed: boolean }) => void = () => {};
  jest.mocked(checkResourceAction).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
  const view = renderHook(({ scope, selection }) => useKnowledgeSpaceAccess(selection, scope), {
    ...setup(), initialProps: { scope: 'old', selection: [space] },
  });
  mockUser = 'admin';
  view.rerender({ scope: 'new', selection: [other] });
  await waitFor(() => expect(view.result.current.blocked).toBe(false));
  await act(async () => resolveOld({ allowed: false }));
  expect(view.result.current.available).toEqual([other]);
  expect(view.result.current.message).toBe('');
});

test('empty and organization-only selections need no space permission request', () => {
  const { result } = renderHook(() => useKnowledgeSpaceAccess([org], 'org'), setup());
  expect(result.current.blocked).toBe(false);
  expect(checkResourceAction).not.toHaveBeenCalled();
});
