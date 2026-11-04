/** T072 覆盖 AC-10, AC-11, AC-13, AC-14, AC-21, AC-25。实际 mutation→API→AuthContext。 */
import React from 'react';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthContextProvider, useAuthContext } from './AuthContext';
import { kunlianSession } from '~/utils/kunlianSession';

const mockUser = { id: '17', role: 'USER' };
const mockSetUser = jest.fn();
const mockClearStates = jest.fn();
const mockNavigate = jest.fn();
jest.mock('axios', () => {
  const actual = jest.requireActual('axios'); const instance = actual.create();
  return { __esModule: true, ...actual, default: { ...actual, create: () => instance } };
});
jest.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate }));
jest.mock('recoil', () => ({ useRecoilState: () => [mockUser, mockSetUser], useResetRecoilState: () => jest.fn(), useSetRecoilState: () => jest.fn() }));
jest.mock('~/store', () => ({ __esModule: true, default: { user: 'user', defaultPreset: 'preset', queriesEnabled: 'queries' } }));
jest.mock('~/hooks/Config/useClearStates', () => ({ __esModule: true, default: () => mockClearStates }));
jest.mock('~/types/chat', () => ({ MutationKeys: { logoutUser: 'logoutUser' }, QueryKeys: {}, dataService: {}, request: {}, setTokenHeader: jest.fn(), SystemRoles: { USER: 'USER', ADMIN: 'ADMIN' } }));
jest.mock('~/hooks/queries/data-provider', () => ({
  useLogoutUserMutation: jest.requireActual('~/hooks/queries/auth/mutations').useLogoutUserMutation,
  useGetRole: () => ({ data: null }), useGetBsConfig: () => ({ data: { host: 'https://old-app.fixture.invalid' } }),
  useGetUserQuery: () => ({ isFetched: true, isSuccess: false }),
  useLoginUserMutation: () => ({ mutate: jest.fn() }), useRefreshTokenMutation: () => ({ mutate: jest.fn() }),
}));
jest.mock('i18next', () => ({ __esModule: true, default: { exists: () => false, t: (key: string) => key } }));
jest.mock('~/utils/loginRedirect', () => ({ redirectToLogin: jest.fn(), buildReturnTo: () => `${globalThis.location.pathname}${globalThis.location.search}` }));
jest.mock('./useTimeout', () => ({ __esModule: true, default: () => jest.fn() }));
jest.mock('~/hooks', () => ({ useAuthContext: () => ({ isAuthenticated: false, isUserLoading: false, user: undefined }) }));
jest.mock('~/components/Auth', () => ({ LoginHandoff: ({ state, onLogin }: { state: string; onLogin: () => void }) => <button onClick={onLogin}>{state}</button> }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => null }));

const transport = (jest.requireMock('axios') as typeof import('axios')).default.create();
const clients: QueryClient[] = [];
beforeEach(() => {
  localStorage.clear(); kunlianSession.confirmUser({ auth_source: 'kunlian' });
  Object.defineProperty(window, 'location', { configurable: true, writable: true, value: {
    origin: 'http://localhost:3080', pathname: '/workspace/c/fixture', search: '', hash: '', href: 'http://localhost:3080/workspace/c/fixture',
  } });
  localStorage.setItem('THIRD_PARTY_LOGOUT_URL', 'https://old-idp.fixture.invalid');
  localStorage.setItem('bs:auth-state', '17');
});
afterEach(() => { clients.forEach(client => client.clear()); clients.length = 0; jest.restoreAllMocks(); });

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 }, mutations: { retry: false } }, logger: { log: () => undefined, warn: () => undefined, error: () => undefined } });
  clients.push(client);
  const clear = jest.spyOn(client, 'removeQueries');
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}><AuthContextProvider>{children}</AuthContextProvider></QueryClientProvider>;
  const hook = renderHook(() => useAuthContext(), { wrapper });
  mockSetUser.mockClear(); mockClearStates.mockClear();
  return { ...hook, clear };
}

it('submits the actual API result after local success and clears queries only then', async () => {
  const calls: string[] = [];
  transport.defaults.adapter = async config => {
    calls.push(config.url!);
    const data = config.url!.endsWith('/csrf') ? { auth_source: 'kunlian', csrf_token: 'c'.repeat(64) }
      : { auth_source: 'kunlian', local_logged_out: true, next_action: { kind: 'kunlian_logout', method: 'POST', url: '/api/kunlian/logout', ticket: 't'.repeat(43) } };
    return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data } };
  };
  const submit = jest.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => undefined);
  const { result, clear } = mount(); act(() => { result.current.logout(); });
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(calls).toContain('/api/v1/user/logout'); expect(mockSetUser).toHaveBeenCalledWith(undefined);
  expect(clear).toHaveBeenCalledTimes(1); expect(mockClearStates).toHaveBeenCalledTimes(1);
  expect(location.href).toBe('http://localhost:3080/workspace/c/fixture');
});

it('retains user, query cache and retry ability when the actual logout request fails', async () => {
  let posts = 0;
  transport.defaults.adapter = async config => {
    if (config.url!.endsWith('/csrf')) return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: { auth_source: 'kunlian', csrf_token: 'c'.repeat(64) } } };
    posts += 1;
    throw Object.assign(new Error('fixture-private-SQL'), { config, response: { config, status: 503, data: { status_code: 19324, data: { reason_code: 'DEPENDENCY_UNAVAILABLE' } } } });
  };
  const { result, clear } = mount(); act(() => { result.current.logout(); });
  await waitFor(() => expect(posts).toBe(1));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(clear).not.toHaveBeenCalled(); expect(mockClearStates).not.toHaveBeenCalled(); expect(mockSetUser).not.toHaveBeenCalledWith(undefined);
  expect(localStorage.getItem('bs:auth-state')).toBe('17'); expect(location.href).toBe('http://localhost:3080/workspace/c/fixture');
  act(() => { result.current.logout(); }); await waitFor(() => expect(posts).toBe(2));
});

it('keeps a user-info dependency failure at its route until the user chooses to retry login', async () => {
  transport.defaults.adapter = async config => { throw Object.assign(new Error('unavailable'), { config, response: { config, status: 503, data: { status_code: 19324, data: { reason_code: 'DEPENDENCY_UNAVAILABLE' } } } }); };
  const request = (await import('~/api/request')).default;
  await expect(request.get('/api/v1/user/info')).rejects.toMatchObject({ httpStatus: 503 });
  const { RequireLogin } = await import('~/routes/RequireLogin');
  const { redirectToLogin } = jest.requireMock('~/utils/loginRedirect');
  render(<RequireLogin><span>protected-content</span></RequireLogin>);
  expect(redirectToLogin).not.toHaveBeenCalled();
  expect(screen.queryByText('protected-content')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button'));
  expect(redirectToLogin).toHaveBeenCalledWith('/workspace/c/fixture', { force: true });
});
