import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { buildKunlianWorkflowEditPath, KUNLIAN_WORKFLOW_ATTEMPT_KEY } from '@bisheng/api-client';

// 覆盖 AC: AC-01, AC-05, AC-06, AC-07, AC-08, AC-10.

const api = vi.hoisted(() => ({ info: vi.fn(), sso: vi.fn() }));
vi.mock('@/controllers/API/user', () => ({ getUserInfo: api.info, logoutApi: vi.fn(), getCaptchaApi: async () => ({}), loginApi: vi.fn(), registerApi: vi.fn() }));
vi.mock('@/controllers/API/pro', () => ({ getSSOurlApi: api.sso, ldapLoginApi: vi.fn() }));
vi.mock('@/controllers/API', () => ({ getComponents: vi.fn(), delComponentApi: vi.fn(), overridComponent: vi.fn(), saveComponent: vi.fn() }));
vi.mock('@/routes', () => ({ resolveRoutePermissions: (user: { web_menu?: string[] }) => user.web_menu ?? [], resolveAdminLandingPath: () => '/' }));
vi.mock('@/utils/brand', () => ({ getBrandAssetUrl: () => '' }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }));
vi.mock('@bisheng/ui', async () => {
  const React = await import('react');
  return {
    Button: ({ children, onClick, disabled }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button onClick={onClick} disabled={disabled}>{children}</button>,
    Input: React.forwardRef<HTMLInputElement>((_, ref) => <input ref={ref} />),
    Checkbox: () => null, notification: { open: vi.fn() }, toast: { show: vi.fn() },
  };
});

const target = buildKunlianWorkflowEditPath('a'.repeat(32));
const loginUrl = `/api/oauth2/kunlian?return_to=${encodeURIComponent(target)}`;
beforeEach(() => {
  vi.resetModules(); localStorage.clear(); sessionStorage.clear(); api.info.mockReset(); api.sso.mockReset();
  api.sso.mockResolvedValue({ kunlian: '/api/oauth2/kunlian', redirect_login_url: 'https://old-idp.fixture.invalid' });
  api.info.mockRejectedValue({ httpStatus: 401 });
  vi.stubGlobal('location', { origin: 'https://app.fixture.invalid', pathname: target.split('?')[0], search: `?${target.split('?')[1]}`, hash: '', href: `https://app.fixture.invalid${target}`, assign: vi.fn(), replace: vi.fn() });
  vi.stubGlobal('history', { state: null, pushState: vi.fn(), replaceState: vi.fn() });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function openEntry() {
  const { UserProvider, userContext } = await import('@/contexts/userContext');
  const { LoginPage } = await import('@/pages/LoginPage/login');
  const { MemoryRouter } = await import('react-router-dom');
  await act(async () => { render(<UserProvider><MemoryRouter initialEntries={[location.pathname + location.search]}>
    <userContext.Consumer>{({ user }) => user?.user_id ? <div>editor-ready</div> : user === null ? <LoginPage /> : null}</userContext.Consumer>
  </MemoryRouter></UserProvider>); });
}

it('confirms an existing user, clears only this attempt and ignores stale global returns', async () => {
  sessionStorage.setItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY, JSON.stringify({ kind: 'edit', workflowId: 'a'.repeat(32), returnTo: target, startedAt: Date.now() }));
  localStorage.setItem('LOGIN_PATHNAME', '/workspace/old');
  api.info.mockResolvedValue({ user_id: 17, has_admin_console: true, web_menu: ['build'] });
  await openEntry(); await screen.findByText('editor-ready');
  expect(sessionStorage.getItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY)).toBeNull();
  expect(localStorage.getItem('LOGIN_PATHNAME')).toBeNull();
  expect(api.sso).not.toHaveBeenCalled(); expect(location.assign).not.toHaveBeenCalled();
  const { workflowManagementReturnTarget } = await import('@/utils/workflowManagement');
  expect(workflowManagementReturnTarget(location.search)).toBe('/build/workflows');
});

it('authorizes only once for the original editor target across remounts', async () => {
  localStorage.setItem('LOGIN_PATHNAME', '/workspace/old');
  localStorage.setItem('THIRD_PARTY_LOGIN_URL', 'https://old-idp.fixture.invalid');
  await openEntry(); await waitFor(() => expect(location.assign).toHaveBeenCalledWith(loginUrl));
  cleanup(); await openEntry(); await screen.findByRole('button', { name: 'shared:kunlian.login' });
  expect(location.assign).toHaveBeenCalledOnce(); expect(location.href).toBe(`https://app.fixture.invalid${target}`);
});

it.each([401, 200])('starts the first SSO for a typed expired session over HTTP %i', async httpStatus => {
  api.info.mockRejectedValue({ httpStatus, status_code: 19323, data: { reason_code: 'SESSION_EXPIRED' } });
  await openEntry(); await waitFor(() => expect(location.assign).toHaveBeenCalledWith(loginUrl));
  expect(location.assign).toHaveBeenCalledOnce();
});

it('keeps a safe manual login available when browser storage is disabled', async () => {
  for (const method of ['getItem', 'setItem', 'removeItem'] as const) {
    vi.spyOn(Storage.prototype, method).mockImplementation(() => { throw new Error('storage-disabled'); });
  }
  await openEntry();
  const retry = await screen.findByRole('button', { name: 'shared:kunlian.login' });
  expect(location.assign).not.toHaveBeenCalled();
  fireEvent.click(retry); expect(location.href).toBe(loginUrl);
});

it.each(['callback', 'directory', 'network', 'status', 'unconfigured'] as const)(
  'stops automatic SSO on %s and keeps manual retry bound to the safe original target', async failure => {
    if (failure === 'callback') location.hash = '#kunlian-login';
    if (failure === 'directory') api.info.mockRejectedValue({ httpStatus: 409, status_code: 19321, data: { reason_code: 'DIRECTORY_NOT_READY' } });
    if (failure === 'network') api.info.mockRejectedValue(new Error('private-network-detail'));
    if (failure === 'status') location.search += '&status_code=19320';
    if (failure === 'unconfigured') api.sso.mockResolvedValue({ kunlian: 'https://attacker.invalid' });
    localStorage.setItem('LOGIN_PATHNAME', '/workspace/old');
    await openEntry();
    if (failure === 'unconfigured') {
      await screen.findByRole('alert');
      expect(screen.queryByRole('button', { name: 'shared:kunlian.login' })).toBeNull();
    } else {
      const retry = await screen.findByRole('button', { name: 'shared:kunlian.login' });
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(location.assign).not.toHaveBeenCalled();
      fireEvent.click(retry); expect(location.href).toBe(loginUrl);
      expect(JSON.parse(sessionStorage.getItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY)!)).toMatchObject({ returnTo: target });
    }
    expect(location.assign).not.toHaveBeenCalled();
  },
);

it.each(['token=private-token', 'tenant_id=7', 'return_to=https%3A%2F%2Fevil.invalid'])(
  'rejects unsafe editor parameters before token import: %s', async query => {
    location.search += `&${query}`;
    const cookie = vi.spyOn(document, 'cookie', 'set');
    await openEntry();
    expect(api.info).not.toHaveBeenCalled(); expect(cookie).not.toHaveBeenCalled();
    expect(history.replaceState).toHaveBeenCalledWith(null, '', '/403');
    expect(location.assign).not.toHaveBeenCalled();
  },
);

it.each([
  { has_admin_console: false, has_workbench: true, web_menu: ['build'] },
  { has_admin_console: true, web_menu: ['knowledge'] },
])('denies missing platform/build eligibility without workspace or IdP redirection', async grants => {
  api.info.mockResolvedValue({ user_id: 17, role: 'user', ...grants });
  await openEntry(); await waitFor(() => expect(history.replaceState).toHaveBeenCalledWith(null, '', '/403'));
  expect(location.replace).not.toHaveBeenCalled(); expect(location.assign).not.toHaveBeenCalled();
});

it.each([
  [503, 19324, 'DEPENDENCY_UNAVAILABLE'],
  [200, 19321, 'DIRECTORY_NOT_READY'],
] as const)('hands later identity failure HTTP %i/%i to the page owner and keeps retry manual', async (status, code, reason) => {
  api.info.mockResolvedValue({ user_id: 17, has_admin_console: true, web_menu: ['build'] });
  await openEntry(); await screen.findByText('editor-ready');
  const request = (await import('@/controllers/request')).default;
  request.defaults.adapter = async config => {
    const data = { status_code: code, data: { reason_code: reason } };
    if (status === 200) return { config, status, statusText: 'OK', headers: {}, data };
    throw Object.assign(new Error('private-detail'), { config, response: { config, status, data } });
  };
  await act(async () => { await expect(request.get('/api/v1/workflow/fixture')).rejects.toMatchObject({ status_code: code }); });
  await screen.findByRole('button', { name: 'shared:kunlian.login' });
  expect(screen.getByRole('alert')).toHaveTextContent(`api_errors:${code}`);
  expect(screen.queryByText('editor-ready')).toBeNull(); expect(location.assign).not.toHaveBeenCalled();
});
