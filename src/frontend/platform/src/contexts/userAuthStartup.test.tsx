import { act, render, screen, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useContext, useEffect } from 'react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import type { AuthEvent } from '@bisheng/api-client';
import { UserProvider, userContext } from './userContext';
import { useAuthSessionStore } from '@/store/authSessionStore';

const mocks = vi.hoisted(() => ({ initialize: vi.fn(), hostPending: false, getUser: vi.fn(), subscription: undefined as ((event?: AuthEvent) => void) | undefined, business: vi.fn() }));
vi.mock('@/controllers/request', () => ({ platformAuth: { initialize: mocks.initialize, get hostPending() { return mocks.hostPending; }, subscribe: (listener: (event?: AuthEvent) => void) => { mocks.subscription = listener; return () => {}; } }, requestInterceptor: {}, markSessionKickAck: vi.fn() }));
vi.mock('@/controllers/API/user', () => ({ getUserInfo: mocks.getUser, logoutApi: vi.fn() }));
vi.mock('@/controllers/API', () => ({ delComponentApi: vi.fn(), getComponents: vi.fn(), overridComponent: vi.fn(), saveComponent: vi.fn() }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }));
vi.mock('@/hooks/useCurrentIdentityRefresh', () => ({ useCurrentIdentityRefresh: vi.fn() }));
vi.mock('@/routes', () => ({ resolveAdminLandingPath: () => '/admin', resolveRoutePermissions: () => [] }));
vi.mock('@bisheng/ui', () => ({ notification: { open: vi.fn() } }));
vi.mock('i18next', () => ({ default: { t: (key: string) => key } }));
const profile = (name: string) => ({ user_id: name, user_name: name, role: 'admin', has_admin_console: true });
function Child() {
  const { user } = useContext(userContext);
  useEffect(() => { mocks.business(); }, []);
  return <p>{user?.user_name ?? 'anonymous'}</p>;
}
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><UserProvider><Child /></UserProvider></QueryClientProvider>);
  return client;
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthSessionStore.setState({ phase: 'loading', session: null });
  mocks.subscription = undefined;
  mocks.hostPending = false;
  const values = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) });
  mocks.getUser.mockResolvedValue(profile('Alice'));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('does not mount business consumers until gateway binding initialization completes', async () => {
  let finish: ((value: null) => void) | undefined;
  mocks.initialize.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  mount();
  expect(mocks.business).not.toHaveBeenCalled();
  expect(mocks.getUser).not.toHaveBeenCalled();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.queryByText('platformAuth.loading')).not.toBeInTheDocument();
  await act(async () => { finish?.(null); });
  await screen.findByText('Alice');
  expect(mocks.business).toHaveBeenCalledOnce();
});
it('clears cached business data and old identity on cross-tab logout', async () => {
  mocks.initialize.mockResolvedValue(null);
  const client = mount();
  await screen.findByText('Alice');
  client.setQueryData(['old-account-business'], { private: true });
  await act(async () => { mocks.subscription?.({ type: 'logout', session: 'a'.repeat(32) }); });
  expect(screen.getByText('anonymous')).toBeInTheDocument();
  expect(client.getQueryData(['old-account-business'])).toBeUndefined();
});
it.each([null, 'a'.repeat(32)])('opens the anonymous route when startup rejects session %s', async session => {
  let finish: ((value: null) => void) | undefined;
  mocks.initialize.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  mount();
  expect(mocks.business).not.toHaveBeenCalled();
  await act(async () => {
    mocks.subscription?.({ type: 'logout', session });
    finish?.(null);
  });
  await screen.findByText('anonymous');
  expect(mocks.getUser).not.toHaveBeenCalled();
  expect(mocks.business).toHaveBeenCalledOnce();
});
it('reloads identity after cross-tab login and rejects a late old identity response', async () => {
  mocks.initialize.mockResolvedValue(null);
  let finishOld: ((value: ReturnType<typeof profile>) => void) | undefined;
  mocks.getUser.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }))
    .mockResolvedValue(profile('Bob'));
  const client = mount();
  await waitFor(() => expect(finishOld).toBeDefined());
  client.setQueryData(['old-account-business'], { private: true });
  await act(async () => { mocks.subscription?.({ type: 'login', session: 'b'.repeat(32) }); });
  await screen.findByText('Bob');
  await act(async () => { finishOld?.(profile('Alice')); });
  expect(screen.queryByText('Alice')).not.toBeInTheDocument();
  expect(screen.getByText('Bob')).toBeInTheDocument();
  expect(client.getQueryData(['old-account-business'])).toBeUndefined();
});
it('shows a retry action on service failure without mounting business consumers', async () => {
  mocks.initialize.mockRejectedValue({ retryable: true });
  mount();
  await screen.findByRole('button', { name: 'platformAuth.retry' });
  expect(mocks.business).not.toHaveBeenCalled();
});

it('keeps a cold host WebView behind the reconnect gate without identity or business queries', async () => {
  mocks.hostPending = true;
  mocks.initialize.mockResolvedValue(null);
  mount();
  await screen.findByText('platformAuth.hostReconnect');
  expect(mocks.getUser).not.toHaveBeenCalled();
  expect(mocks.business).not.toHaveBeenCalled();
});
