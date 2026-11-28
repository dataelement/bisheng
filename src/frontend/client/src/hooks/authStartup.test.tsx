import { act, render, screen, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ComponentType, PropsWithChildren } from 'react';
// Exercise the existing state model with its real test provider.
const { RecoilRoot } = jest.requireActual<{ RecoilRoot: ComponentType<PropsWithChildren> }>('recoil');
import { MemoryRouter } from 'react-router-dom';
import type { AuthEvent, AuthSessionMetadata } from '@bisheng/api-client';
import { AuthContextProvider, useAuthContext } from './AuthContext';

let mockHostPending = false;
let mockSnapshot: AuthSessionMetadata | null = null;
const mockTranslate = (key: string) => key;
let mockSubscription: ((event?: AuthEvent) => void) | undefined;
const mockInitialize = jest.fn();
const mockGetUser = jest.fn();
const mockRefresh = jest.fn().mockResolvedValue(false);
jest.mock('~/api/request', () => ({ platformAuth: {
  initialize: (...args: unknown[]) => mockInitialize(...args), refresh: (...args: unknown[]) => mockRefresh(...args),
  get snapshot() { return mockSnapshot; }, get hostPending() { return mockHostPending; }, subscribe: (listener: (event?: AuthEvent) => void) => { mockSubscription = listener; return () => {}; },
} }));
jest.mock('~/types/chat', () => ({ SystemRoles: { USER: 'USER', ADMIN: 'ADMIN' }, setTokenHeader: jest.fn() }));
jest.mock('~/store', () => ({ __esModule: true, default: jest.requireActual('~/store/user').default }));
jest.mock('~/hooks/queries/data-provider', () => ({
  useGetBsConfig: () => ({ data: { host: '/' } }), useGetRole: () => ({ data: null }),
  useLoginUserMutation: () => ({ mutate: jest.fn() }), useLogoutUserMutation: () => ({ mutate: jest.fn() }),
  useGetUserQuery: (config: { enabled: boolean }) => jest.requireActual('@tanstack/react-query').useQuery(['user'], () => mockGetUser(), { enabled: config.enabled, retry: false }),
}));
jest.mock('react-i18next', () => ({ useTranslation: () => ({ t: mockTranslate }) }));
const profile = (name: string) => ({ id: name, _id: name, name, role: 'USER' });
function Child() {
  const context = useAuthContext();
  return <p>{context.user?.name ?? 'anonymous'}|{String(context.isAuthenticated)}</p>;
}
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } }, logger: { log: () => {}, warn: console.warn, error: () => {} } });
  render(<QueryClientProvider client={client}><RecoilRoot><MemoryRouter>
    <AuthContextProvider authConfig={{ test: true, loginRedirect: '' }}><Child /></AuthContextProvider>
  </MemoryRouter></RecoilRoot></QueryClientProvider>);
  return client;
}
beforeEach(() => { mockHostPending = false; mockSnapshot = null; mockSubscription = undefined; mockInitialize.mockReset(); mockGetUser.mockReset(); mockGetUser.mockResolvedValue(profile('Alice')); });
afterEach(cleanup);
it('waits for shared initialization before the identity query or route consumers mount', async () => {
  let finish: ((value: null) => void) | undefined;
  mockInitialize.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  mount();
  expect(mockGetUser).not.toHaveBeenCalled();
  expect(screen.queryByText('anonymous|false')).not.toBeInTheDocument();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.queryByText('platformAuth.loading')).not.toBeInTheDocument();
  await act(async () => { finish?.(null); });
  await screen.findByText('Alice|true');
});
it('clears old identity and cached business data on cross-tab logout', async () => {
  mockInitialize.mockResolvedValue(null);
  const client = mount();
  await screen.findByText('Alice|true');
  client.setQueryData(['old-account-business'], { private: true });
  mockGetUser.mockRejectedValue(new Error('signed out'));
  await act(async () => { mockSubscription?.({ type: 'logout', session: 'a'.repeat(32) }); });
  await screen.findByText('anonymous|false');
  expect(client.getQueryData(['old-account-business'])).toBeUndefined();
});
it('fetches the new account after cross-tab login and fences late old query results', async () => {
  mockInitialize.mockResolvedValue(null);
  let oldFinish: ((value: ReturnType<typeof profile>) => void) | undefined;
  mockGetUser.mockImplementationOnce(() => new Promise(resolve => { oldFinish = resolve; }))
    .mockResolvedValue(profile('Bob'));
  const client = mount();
  await waitFor(() => expect(oldFinish).toBeDefined());
  client.setQueryData(['old-account-business'], { private: true });
  await act(async () => { mockSubscription?.({ type: 'login', session: 'b'.repeat(32) }); });
  await screen.findByText('Bob|true');
  await act(async () => { oldFinish?.(profile('Alice')); });
  expect(screen.queryByText('Alice|true')).not.toBeInTheDocument();
  expect(client.getQueryData(['old-account-business'])).toBeUndefined();
});
it('ignores late tokenUpdated events after logout', async () => {
  mockInitialize.mockResolvedValue(null);
  mount();
  await screen.findByText('Alice|true');
  mockGetUser.mockRejectedValue(new Error('signed out'));
  await act(async () => { mockSubscription?.({ type: 'logout', session: 'a'.repeat(32) }); });
  await screen.findByText('anonymous|false');
  const calls = mockInitialize.mock.calls.length;
  await act(async () => { window.dispatchEvent(new CustomEvent('tokenUpdated', { detail: 'old-token' })); });
  expect(mockInitialize).toHaveBeenCalledTimes(calls);
  expect(screen.getByText('anonymous|false')).toBeInTheDocument();
});

it('does not query identity or mount routes while the mobile host restores a cold WebView', async () => {
  mockHostPending = true;
  mockInitialize.mockResolvedValue(null);
  mount();
  await screen.findByText('platformAuth.hostReconnect');
  expect(mockGetUser).not.toHaveBeenCalled();
  expect(screen.queryByText('anonymous|false')).not.toBeInTheDocument();
});

const hostSession: AuthSessionMetadata = {
  session_id: 'a'.repeat(32), refresh_mode: 'host', delivery_state: 'BOUND',
  access_expires_at: '2027-01-01T00:00:00Z', session_expires_at: '2027-02-01T00:00:00Z', refresh_expires_at: null,
};

it('resumes identity and routes after the host replaces an expired cold WebView credential', async () => {
  mockHostPending = true;
  mockInitialize.mockImplementation(async (force?: boolean) => {
    if (!force) return null;
    mockHostPending = false;
    mockSnapshot = hostSession;
    return hostSession;
  });
  mount();
  await screen.findByText('platformAuth.hostReconnect');
  expect(mockGetUser).not.toHaveBeenCalled();
  await act(async () => { window.dispatchEvent(new CustomEvent('tokenUpdated')); });
  await screen.findByText('Alice|true');
  expect(mockInitialize).toHaveBeenCalledWith(true);
  expect(screen.queryByText('platformAuth.hostReconnect')).not.toBeInTheDocument();
});

it('keeps a pending host connection retryable after a temporary renewal failure', async () => {
  mockHostPending = true;
  mockInitialize.mockImplementation(async (force?: boolean) => {
    if (force) throw new Error('network unavailable');
    return null;
  });
  mount();
  await screen.findByText('platformAuth.hostReconnect');
  await act(async () => { window.dispatchEvent(new CustomEvent('tokenUpdated')); });
  expect(screen.getByText('platformAuth.hostReconnect')).toBeInTheDocument();
  expect(mockHostPending).toBe(true);
  expect(mockGetUser).not.toHaveBeenCalled();
});

it('does not restore a host identity when logout wins an in-flight renewal', async () => {
  mockHostPending = true;
  let finish: ((session: null) => void) | undefined;
  mockInitialize.mockImplementation((force?: boolean) => force
    ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(null));
  mount();
  await screen.findByText('platformAuth.hostReconnect');
  await act(async () => { window.dispatchEvent(new CustomEvent('tokenUpdated')); });
  expect(finish).toBeDefined();
  mockGetUser.mockRejectedValue(new Error('signed out'));
  mockHostPending = false;
  await act(async () => { mockSubscription?.({ type: 'logout', session: hostSession.session_id }); });
  await screen.findByText('anonymous|false');
  // The shared controller fences an initialization that lost to logout with null.
  await act(async () => { finish?.(null); });
  expect(screen.getByText('anonymous|false')).toBeInTheDocument();
});
