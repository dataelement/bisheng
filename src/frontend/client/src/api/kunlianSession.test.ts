/** T072 覆盖 AC-01, AC-04, AC-07, AC-08, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25。 */
jest.mock('axios', () => {
  const actual = jest.requireActual('axios'); const instance = actual.create();
  return { __esModule: true, ...actual, default: { ...actual, create: () => instance } };
});
jest.mock('~/utils/loginRedirect', () => ({ redirectToLogin: jest.fn() }));
jest.mock('i18next', () => ({ __esModule: true, default: { exists: () => false, t: (key: string) => key } }));

beforeEach(() => {
  jest.resetModules(); localStorage.clear(); sessionStorage.clear();
  Object.defineProperty(window, 'location', { configurable: true, writable: true, value: {
    origin: 'http://localhost:3080', pathname: '/workspace/c/fixture', search: '?tab=run', hash: '', href: 'http://localhost:3080/workspace/c/fixture?tab=run',
  } });
  window.showToast = jest.fn();
});

async function setup(confirmed = true) {
  const request = (await import('./request')).default;
  const transport = (jest.requireMock('axios') as typeof import('axios')).default.create();
  transport.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: { auth_source: 'kunlian', user_id: 17 } } });
  if (confirmed) await request.get('/api/v1/user/info');
  return { request, transport };
}

it('keeps the legacy logout path after a generic unauthenticated protocol probe', async () => {
  const { transport } = await setup(false);
  const paths: string[] = [];
  transport.defaults.adapter = async config => {
    paths.push(config.url!);
    if (config.url!.endsWith('/session/csrf')) {
      throw Object.assign(new Error('ordinary authentication required'), {
        config, response: { config, status: 401, data: { detail: 'Authentication required' } },
      });
    }
    return { config, status: 201, statusText: 'Created', headers: {}, data: { message: 'legacy logout' } };
  };
  const { logoutUserApi } = await import('./user');
  await expect(logoutUserApi()).resolves.toMatchObject({ message: 'legacy logout' });
  expect(paths).toEqual(['/api/v1/identity-integrations/kunlian/session/csrf', '/api/v1/user/logout']);
});

it('confirms server source, strips ambient Bearer, and carries CSRF in the actual write', async () => {
  const { request, transport } = await setup();
  const captured: { url: string; authorization: unknown; csrf: unknown }[] = [];
  transport.defaults.adapter = async config => {
    captured.push({ url: config.url!, authorization: config.headers.Authorization, csrf: config.headers['X-CSRF-Token'] });
    return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: { auth_source: 'kunlian', csrf_token: 'c'.repeat(64) } } };
  };
  await request.post('/api/v1/workflow/create', {}, { headers: { Authorization: 'Bearer old' } });
  expect(captured).toHaveLength(2); expect(captured[1].authorization).toBeUndefined(); expect(captured[1].csrf).toBe('c'.repeat(64));
});

it.each([[409,19321,'DIRECTORY_NOT_READY'],[403,19322,'IDENTITY_UNAVAILABLE'],[503,19324,'DEPENDENCY_UNAVAILABLE']] as const)(
  'keeps HTTP %i failures rejected without redirecting to old authentication', async (status, code, reason) => {
    const { request, transport } = await setup();
    localStorage.setItem('THIRD_PARTY_LOGIN_URL', 'https://old-idp.fixture.invalid');
    transport.defaults.adapter = async config => { throw Object.assign(new Error('upstream-private-detail'), { config, response: { config, status, data: { status_code: code, status_message: 'upstream-private-detail', data: { reason_code: reason } } } }); };
    const errors = await Promise.all([request.get('/one'), request.get('/two')].map(promise => promise.catch(error => error)));
    for (const error of errors) expect(error).toMatchObject({ name: 'ApiError', httpStatus: status });
    expect(window.showToast).toHaveBeenCalledTimes(1); expect(location.href).toBe('http://localhost:3080/workspace/c/fixture?tab=run');
  },
);

it('uses fixed reauthorization only for the matching SESSION_EXPIRED contract', async () => {
  const { request, transport } = await setup();
  transport.defaults.adapter = async config => { throw Object.assign(new Error('expired'), { config, response: { config, status: 401, data: { status_code: 19323, data: { reason_code: 'SESSION_EXPIRED' } } } }); };
  await expect(request.get('/api/v1/probe')).rejects.toMatchObject({ httpStatus: 401 });
  expect(location.href).toBe('/api/oauth2/kunlian?return_to=%2Fworkspace%2Fc%2Ffixture%3Ftab%3Drun');
});

it('carries the local logout result out of the actual user API and preserves failures', async () => {
  const { transport } = await setup();
  transport.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: config.url!.endsWith('/csrf')
    ? { auth_source: 'kunlian', csrf_token: 'c'.repeat(64) } : { auth_source: 'kunlian', local_logged_out: true, next_action: { kind: 'kunlian_logout', method: 'POST', url: '/api/kunlian/logout', ticket: 't'.repeat(43) } } } });
  const { logoutUserApi } = await import('./user');
  await expect(logoutUserApi()).resolves.toMatchObject({ auth_source: 'kunlian', local_logged_out: true, next_action: { method: 'POST' } });
  transport.defaults.adapter = async config => { throw Object.assign(new Error('SQL private'), { config, response: { config, status: 503, data: { status_code: 19324, data: { reason_code: 'DEPENDENCY_UNAVAILABLE' } } } }); };
  await expect(logoutUserApi()).rejects.toMatchObject({ httpStatus: 503 });
});

it('clears old transport state before bootstrap and refuses a different server source', async () => {
  location.hash = '#kunlian-login'; localStorage.setItem('ws_token', 'fixture-old-token');
  const replace = jest.spyOn(history, 'replaceState');
  const { request, transport } = await setup(false);
  transport.defaults.headers.common.Authorization = 'Bearer fixture-old-token';
  transport.defaults.adapter = async config => {
    expect(config.headers.Authorization).toBeUndefined();
    return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: { user_id: 999 } } };
  };
  await expect(request.get('/api/v1/user/info')).rejects.toBeInstanceOf(Error);
  expect(localStorage.getItem('ws_token')).toBeNull(); expect(replace).toHaveBeenCalled();
  replace.mockRestore();
});

it('distinguishes an unavailable Kunlian user-info response from ordinary directory management', async () => {
  const { request, transport } = await setup(false);
  const { kunlianSession } = await import('~/utils/kunlianSession');
  transport.defaults.adapter = async config => { throw Object.assign(new Error('denied'), { config, response: { config, status: 403, data: { status_code: 19322, data: { reason_code: 'IDENTITY_UNAVAILABLE' } } } }); };
  await expect(request.get('/api/v1/identity-integrations/kunlian/status')).rejects.toMatchObject({ httpStatus: 403 });
  expect(kunlianSession.isKunlian()).toBe(false);
  await expect(request.get('/api/v1/user/info')).rejects.toMatchObject({ httpStatus: 403 });
  expect(kunlianSession.isKunlian()).toBe(true);
});
