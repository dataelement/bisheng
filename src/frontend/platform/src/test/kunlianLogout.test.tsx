import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';

/** 覆盖 AC-10, AC-13, AC-14, AC-21, AC-25。 */
const api = vi.hoisted(() => ({ logout: vi.fn(), getInfo: vi.fn(), confirm: vi.fn(), sso: vi.fn() }));
vi.mock('@/controllers/API/user', () => ({ logoutApi: api.logout, getUserInfo: api.getInfo, getCaptchaApi: async () => ({ user_capthca: false }), loginApi: vi.fn(), registerApi: vi.fn() }));
vi.mock('@/controllers/API/pro', () => ({ getSSOurlApi: api.sso, ldapLoginApi: vi.fn() }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: api.confirm }));
vi.mock('@/controllers/API', () => ({ getComponents: vi.fn(), delComponentApi: vi.fn(), overridComponent: vi.fn(), saveComponent: vi.fn() }));
vi.mock('@/routes', () => ({ resolveRoutePermissions: () => [], resolveAdminLandingPath: () => '/' }));
vi.mock('@/components/HeaderTenantScope', () => ({ HeaderTenantScope: () => null }));
vi.mock('@/layout/HeaderMenu', () => ({ HeaderMenu: () => null }));
vi.mock('@/layout/LicenseBanner', () => ({ LicenseBanner: () => null }));
vi.mock('@/hooks/useDshBrowserConfig', () => ({ useDshBrowserConfig: () => ({ config: null }) }));
vi.mock('@/components/bs-comp/formFields/useSelectLabels', () => ({ useSelectLabels: () => ({}) }));
vi.mock('@/utils/brand', () => ({ getBrandAssetUrl: () => '' }));
vi.mock('@bisheng/ui', async () => {
  const React = await import('react');
  return {
  Button: ({ children, onClick, disabled }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button onClick={onClick} disabled={disabled}>{children}</button>,
  Input: React.forwardRef<HTMLInputElement>((_, ref) => <input ref={ref} />), Checkbox: () => <input type="checkbox" />,
  Dropdown: ({ menu }: { menu: React.ReactNode }) => <div>{menu}</div>,
  DropdownItem: ({ children, onSelect }: { children: React.ReactNode; onSelect: () => void }) => <button onClick={onSelect}>{children}</button>,
  DropdownChevron: () => null, DropdownSeparator: () => null, Select: () => null,
  Tooltip: ({ children }: { children: React.ReactNode }) => children, TooltipProvider: ({ children }: { children: React.ReactNode }) => children,
  notification: { open: vi.fn() },
  };
});
beforeEach(() => {
  vi.resetModules(); localStorage.clear(); sessionStorage.clear(); api.logout.mockReset(); api.confirm.mockReset();
  api.getInfo.mockImplementation(() => new Promise(() => undefined));
  vi.stubGlobal('location', { origin: 'https://app.fixture.invalid', pathname: '/403', search: '', hash: '', href: 'https://app.fixture.invalid/403' });
});
afterEach(() => {
  document.querySelectorAll('form[hidden][action="/api/kunlian/logout"]').forEach(form => form.remove());
  vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.doUnmock('@/contexts/userContext');
  vi.doUnmock('@/components/bs-comp/chatComponent');
  vi.doUnmock('@/components/bs-comp/chatComponent/messageStore');
  vi.doUnmock('@/store/assistantStore');
});

it('submits a proven logout ticket by fixed POST and never uses a cached third-party logout URL', async () => {
  const { kunlianSession } = await import('@/utils/loginReturnTo');
  kunlianSession.confirmUser({ auth_source: 'kunlian' });
  const submit = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => undefined);
  localStorage.setItem('THIRD_PARTY_LOGOUT_URL', 'https://old-idp.fixture.invalid');
  api.logout.mockResolvedValue({ auth_source: 'kunlian', local_logged_out: true, next_action: { kind: 'kunlian_logout', method: 'POST', url: '/api/kunlian/logout', ticket: 't'.repeat(43) } });
  const { default: Page403 } = await import('@/pages/Page403'); render(<Page403 />);
  fireEvent.click(screen.getByRole('button'));
  await waitFor(() => expect(submit).toHaveBeenCalledOnce());
  const form = submit.mock.contexts[0] as HTMLFormElement; expect(form.method).toBe('post'); expect(form.getAttribute('action')).toBe('/api/kunlian/logout');
  expect(form.querySelector<HTMLInputElement>('input[name=ticket]')?.value).toBe('t'.repeat(43));
  expect(location.href).toBe('https://app.fixture.invalid/403');
});

it('keeps a failed local logout retryable without clearing UI state or navigating in finally', async () => {
  const { kunlianSession } = await import('@/utils/loginReturnTo'); kunlianSession.confirmUser({ auth_source: 'kunlian' });
  localStorage.setItem('isLogin', '1');
  api.logout.mockRejectedValue(new Error('fixture-local-revocation-failed'));
  const { default: Page403 } = await import('@/pages/Page403'); render(<Page403 />);
  fireEvent.click(screen.getByRole('button')); await waitFor(() => expect(api.logout).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.getByRole('button')).not.toBeDisabled());
  expect(localStorage.getItem('isLogin')).toBe('1'); expect(location.href).toBe('https://app.fixture.invalid/403');
});

const success = { auth_source: 'kunlian', local_logged_out: true, next_action: { kind: 'kunlian_logout', method: 'POST', url: '/api/kunlian/logout', ticket: 't'.repeat(43) } };

it('passes the MainLayout confirmation result through the fixed logout action', async () => {
  const { kunlianSession } = await import('@/utils/loginReturnTo'); kunlianSession.confirmUser({ auth_source: 'kunlian' });
  const submit = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => undefined);
  vi.doMock('@/contexts/userContext', async () => {
    const React = await import('react');
    return { userContext: React.createContext({ user: { user_id: 17, role: 'user', web_menu: [] }, setUser: vi.fn() }) };
  });
  api.logout.mockResolvedValue(success);
  const { MemoryRouter } = await import('react-router-dom');
  const { default: MainLayout } = await import('@/layout/MainLayout');
  render(<MemoryRouter><MainLayout /></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: 'menu.logout' }));
  const next = vi.fn(); await act(async () => { await api.confirm.mock.calls[0][0].onOk(next); });
  expect(submit).toHaveBeenCalledOnce(); expect(next).toHaveBeenCalledOnce();
  expect(location.href).toBe('https://app.fixture.invalid/403');
});

it('keeps TenantSelect and kicked-session callers from replacing the logout result', async () => {
  const { kunlianSession } = await import('@/utils/loginReturnTo'); kunlianSession.confirmUser({ auth_source: 'kunlian' });
  const submit = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => undefined);
  api.logout.mockResolvedValue(success);
  const { default: TenantSelect } = await import('@/pages/LoginPage/TenantSelect');
  const view = render(<TenantSelect />); fireEvent.click(screen.getByRole('button', { name: 'tenant.backToLogin' }));
  await waitFor(() => expect(submit).toHaveBeenCalledOnce()); view.unmount(); submit.mockClear();
  const { UserProvider } = await vi.importActual<typeof import('@/contexts/userContext')>('@/contexts/userContext');
  render(<UserProvider><div>probe</div></UserProvider>);
  const { requestInterceptor } = await import('@/controllers/request');
  act(() => { requestInterceptor.remoteLoginFuc?.('fixture-session-kicked'); });
  const next = vi.fn(); await act(async () => { await api.confirm.mock.calls[0][0].onOk(next); });
  expect(submit).toHaveBeenCalledOnce(); expect(next).toHaveBeenCalledOnce();
  expect(location.href).toBe('https://app.fixture.invalid/403');
});

it.each([
  { ...success, local_logged_out: false },
  { ...success, next_action: { ...success.next_action, url: 'https://attacker.invalid' } },
  { ...success, next_action: { ...success.next_action, method: 'GET' } },
])('refuses an unproven result or an arbitrary action without posting a form', async result => {
  const { kunlianSession } = await import('@/utils/loginReturnTo'); kunlianSession.confirmUser({ auth_source: 'kunlian' });
  const submit = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => undefined);
  expect(() => kunlianSession.completeLogout(result)).toThrow(); expect(submit).not.toHaveBeenCalled();
});

it.each([true, false])('keeps the old automatic login separate from the Kunlian flow: %s', async kunlian => {
  const { kunlianSession } = await import('@/utils/loginReturnTo');
  if (kunlian) kunlianSession.expectLocalProtocol();
  api.sso.mockResolvedValue({ kunlian: '/api/oauth2/kunlian', redirect_login_url: 'https://old-idp.fixture.invalid' });
  const { MemoryRouter } = await import('react-router-dom');
  const { LoginPage } = await import('@/pages/LoginPage/login');
  const { locationContext } = await import('@/contexts/locationContext');
  render(<MemoryRouter><locationContext.Consumer>{current => <locationContext.Provider value={{ ...current, appConfig: { ...current.appConfig, isPro: true } }}><LoginPage /></locationContext.Provider>}</locationContext.Consumer></MemoryRouter>);
  if (kunlian) {
    await screen.findByRole('button', { name: 'shared:kunlian.login' });
    expect(location.href).toBe('https://app.fixture.invalid/403');
  } else {
    await waitFor(() => expect(location.href).toBe('https://old-idp.fixture.invalid'));
  }
});

it('creates the assistant debug socket URL without the forbidden t query', async () => {
  const { kunlianSession } = await import('@/utils/loginReturnTo'); kunlianSession.confirmUser({ auth_source: 'kunlian' });
  const captures: string[] = [];
  vi.doMock('@/components/bs-comp/chatComponent', () => ({ default: ({ wsUrl }: { wsUrl: string }) => { captures.push(wsUrl); return null; } }));
  vi.doMock('@/components/bs-comp/chatComponent/messageStore', () => ({ useMessageStore: () => ({ messages: [], changeChatId: vi.fn(), inputLocked: false }) }));
  vi.doMock('@/store/assistantStore', () => ({ useAssistantStore: () => ({ assistantState: { name: 'fixture' } }) }));
  const { default: TestChat } = await import('@/pages/BuildPage/assistant/editAssistant/TestChat');
  render(<TestChat assisId="fixture" guideQuestion={[]} onClear={vi.fn()} />);
  expect(captures).not.toHaveLength(0);
  expect(captures[0]).toContain('/api/v1/assistant/chat/fixture');
  expect(new URL('wss://' + captures[0]).searchParams.has('t')).toBe(false);
});
