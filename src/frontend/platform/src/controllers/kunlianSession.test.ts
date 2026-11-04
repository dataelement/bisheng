import { afterEach, beforeEach, expect, it, vi } from 'vitest';

/** 覆盖 AC-01, AC-04, AC-07, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25。 */
const notices = vi.hoisted(() => vi.fn());
vi.mock('@bisheng/ui', () => ({ notification: { open: notices } }));
beforeEach(() => {
  vi.resetModules(); localStorage.clear(); sessionStorage.clear(); notices.mockClear();
  vi.stubGlobal('location', { origin: 'https://app.fixture.invalid', pathname: '/flow/fixture', search: '?tab=run', hash: '', href: 'https://app.fixture.invalid/flow/fixture?tab=run' });
  vi.stubGlobal('history', { replaceState: vi.fn() });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function confirmedRequest() {
  const module = await import('./request');
  module.default.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: { auth_source: 'kunlian', user_id: 17 } } });
  await module.default.get('/api/v1/user/info');
  return module;
}

it('clears stale Bearer before bootstrap, confirms only server source, and fetches CSRF for the actual write', async () => {
  localStorage.setItem('ws_token', 'fixture-old-token'); location.hash = '#kunlian-login';
  const module = await import('./request');
  const calls: { url: string; authorization: unknown; csrf: unknown }[] = [];
  module.default.defaults.adapter = async config => {
    calls.push({ url: config.url!, authorization: config.headers.Authorization, csrf: config.headers['X-CSRF-Token'] });
    return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: config.url!.endsWith('/csrf') ? { auth_source: 'kunlian', csrf_token: 'c'.repeat(64) } : { auth_source: 'kunlian', user_id: 17 } } };
  };
  await module.default.get('/api/v1/user/info'); await module.default.post('/api/v1/workflow/create', {});
  expect(localStorage.getItem('ws_token')).toBeNull(); expect(history.replaceState).toHaveBeenCalled();
  expect(calls.map(call => call.authorization)).toEqual([undefined, undefined, undefined]);
  expect(calls.at(-1)?.csrf).toBe('c'.repeat(64));
});

it('refuses an ordinary account response after a Kunlian bootstrap hint', async () => {
  location.hash = '#kunlian-login';
  const module = await import('./request');
  module.default.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: { user_id: 999 } } });
  await expect(module.default.get('/api/v1/user/info')).rejects.toBeInstanceOf(Error);
});

it.each([[409,19321,'DIRECTORY_NOT_READY'],[403,19322,'IDENTITY_UNAVAILABLE'],[503,19324,'DEPENDENCY_UNAVAILABLE']] as const)(
  'keeps HTTP %i failures rejected without following old third-party URLs', async (status, code, reason) => {
    const module = await confirmedRequest();
    localStorage.setItem('THIRD_PARTY_LOGIN_URL', 'https://old-idp.fixture.invalid');
    module.default.defaults.adapter = async config => { throw Object.assign(new Error('upstream-private-detail'), { config, response: { config, status, data: { status_code: code, status_message: 'upstream-private-detail', data: { reason_code: reason } } } }); };
    const errors = await Promise.all([module.default.get('/one'), module.default.get('/two')].map(promise => promise.catch(error => error)));
    expect(errors.every(error => error.name === 'ApiError' && error.httpStatus === status)).toBe(true);
    expect(location.href).toBe('https://app.fixture.invalid/flow/fixture?tab=run');
    expect(notices).toHaveBeenCalledTimes(1);
  },
);

it('only a matching SESSION_EXPIRED contract starts one fixed same-origin reauthorization', async () => {
  const module = await confirmedRequest();
  module.default.defaults.adapter = async config => { throw Object.assign(new Error('expired'), { config, response: { config, status: 401, data: { status_code: 19323, data: { reason_code: 'SESSION_EXPIRED' } } } }); };
  await expect(module.default.get('/api/v1/probe')).rejects.toMatchObject({ httpStatus: 401 });
  expect(location.href).toBe('/api/oauth2/kunlian?return_to=%2Fflow%2Ffixture%3Ftab%3Drun');
});

it('does not treat a directory-management rejection as an ordinary administrator identity change', async () => {
  const module = await import('./request');
  const { kunlianSession } = await import('./kunlianSession');
  kunlianSession.confirmUser({ user_id: 17 });
  module.default.defaults.adapter = async config => { throw Object.assign(new Error('denied'), { config, response: { config, status: 409, data: { status_code: 19327, data: { reason_code: 'BINDING_CONFLICT' } } } }); };
  await expect(module.default.get('/api/v1/identity-integrations/kunlian/status')).rejects.toMatchObject({ httpStatus: 409 });
  expect(kunlianSession.isKunlian()).toBe(false);
});

it('uses local protocol to identify a logout when business user info was unavailable', async () => {
  const module = await import('./request');
  const calls: string[] = [];
  module.default.defaults.adapter = async config => {
    calls.push(config.url!);
    const data = config.url!.endsWith('/csrf') ? { auth_source: 'kunlian', csrf_token: 'c'.repeat(64) }
      : { auth_source: 'kunlian', local_logged_out: true, next_action: null };
    return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data } };
  };
  const { logoutApi } = await import('./API/user');
  expect(await logoutApi()).toMatchObject({ auth_source: 'kunlian', local_logged_out: true });
  expect(calls.at(-1)).toBe('/api/v1/user/logout');
});

it('does not require the previous session CSRF to dispatch an explicit password login', async () => {
  const module = await confirmedRequest();
  const urls: string[] = [];
  module.default.defaults.adapter = async config => {
    urls.push(config.url!);
    return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: {} } };
  };
  await module.default.post('/api/v1/user/login', { user_name: 'fixture-local', password: 'fixture-encrypted' });
  expect(urls).toEqual(['/api/v1/user/login']);
});

it('carries CSRF through the real fetch streaming path without a Bearer', async () => {
  const module = await confirmedRequest();
  module.default.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: { auth_source: 'kunlian', csrf_token: 'c'.repeat(64) } } });
  const fetch = vi.fn().mockResolvedValue({ ok: true, headers: new Headers({ 'content-type': 'application/x-ndjson' }), body: new ReadableStream({ start(controller) { controller.close(); } }) });
  vi.stubGlobal('fetch', fetch);
  const { requestStream } = await import('./requestStream');
  const stream = await requestStream('/api/v1/audit');
  expect(fetch.mock.calls[0][1].headers['X-CSRF-Token']).toBe('c'.repeat(64));
  expect(fetch.mock.calls[0][1].headers.Authorization).toBeUndefined();
  await stream.cancel();
});
