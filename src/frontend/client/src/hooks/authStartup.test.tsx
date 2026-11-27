import { act, render, screen, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ComponentType, PropsWithChildren } from 'react';
// Exercise the existing state model with its real test provider.
const { RecoilRoot } = jest.requireActual<{ RecoilRoot: ComponentType<PropsWithChildren> }>('recoil');
import { MemoryRouter } from 'react-router-dom';
import type { AuthEvent } from '@bisheng/api-client';
import { AuthContextProvider, useAuthContext } from './AuthContext';

let mockHostPending = false;
let mockSubscription: ((event?: AuthEvent) => void) | undefined;
const mockInitialize = jest.fn();
const mockGetUser = jest.fn();
const mockRefresh = jest.fn().mockResolvedValue(false);
jest.mock('~/api/request', () => ({ platformAuth: {
  initialize: (...args: unknown[]) => mockInitialize(...args), refresh: (...args: unknown[]) => mockRefresh(...args),
  snapshot: null, get hostPending() { return mockHostPending; }, subscribe: (listener: (event?: AuthEvent) => void) => { mockSubscription = listener; return () => {}; },
} }));
jest.mock('~/types/chat', () => ({ SystemRoles: { USER: 'USER', ADMIN: 'ADMIN' }, setTokenHeader: jest.fn() }));
jest.mock('~/store', () => ({ __esModule: true, default: jest.requireActual('~/store/user').default }));
jest.mock('~/hooks/queries/data-provider', () => ({
  useGetBsConfig: () => ({ data: { host: '/' } }), useGetRole: () => ({ data: null }),
  useLoginUserMutation: () => ({ mutate: jest.fn() }), useLogoutUserMutation: () => ({ mutate: jest.fn() }),
  useGetUserQuery: (config: { enabled: boolean }) => jest.requireActual('@tanstack/react-query').useQuery(['user'], () => mockGetUser(), { enabled: config.enabled, retry: false }),
}));
jest.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
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
beforeEach(() => { mockHostPending = false; mockSubscription = undefined; mockInitialize.mockReset(); mockGetUser.mockReset(); mockGetUser.mockResolvedValue(profile('Alice')); });
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
