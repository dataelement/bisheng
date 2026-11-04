import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const notices = vi.hoisted(() => vi.fn());
vi.mock('@bisheng/ui', () => ({ notification: { open: notices } }));
beforeEach(() => { vi.resetModules(); localStorage.clear(); sessionStorage.clear(); notices.mockClear(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function setup(envelope: unknown) {
  const module = await import('./request');
  module.default.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: envelope });
  return module;
}
it('keeps password-expiration evidence for the login interaction without a generic notice', async () => {
  const { default: request } = await setup({ status_code: 10601, status_message: 'Password expired', data: { user_id: 7 } });
  const error = await request.post('/api/v1/user/login').catch(cause => cause);
  expect(error.name).toBe('ApiError');
  expect(error).toMatchObject({ status_code: 10601, httpStatus: 200, data: { user_id: 7 }, presentation: 'none' });
  expect(notices).not.toHaveBeenCalled();
});
it('preserves the legacy 11010 envelope for its caller-owned interaction', async () => {
  const body = { status_code: 11010, status_message: 'Interaction required', data: { id: 4 } };
  const { default: request } = await setup(body);
  expect(await request.get('/test')).toBe(body);
  expect(notices).not.toHaveBeenCalled();
});
it('throttles concurrent license failures while every caller still receives its own error', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(10000);
  const { default: request, showApiError } = await setup({ status_code: 11001, status_message: 'License expired', data: { license: 'expired' } });
  const errors = await Promise.all([request.get('/one'), request.get('/two')].map(promise => promise.catch(cause => cause)));
  expect(errors[0]).not.toBe(errors[1]);
  errors.forEach(error => { expect(error).toMatchObject({ status_code: 11001, presentation: 'global' }); showApiError(error); });
  expect(notices).toHaveBeenCalledTimes(1);
});
it('keeps forced permission routing for showError=false while the legacy silent exception stays quiet', async () => {
  const current = { href: '/current' };
  vi.stubGlobal('location', current);
  const { default: request } = await setup({ status_code: 403, status_message: 'Forbidden', data: { reason: 'role' } });
  const forced = await request.get('/api/v1/restricted', { showError: false }).catch(cause => cause);
  expect(current.href).toBe('/403');
  expect(forced).toMatchObject({ status_code: 403, presentation: 'global', data: { reason: 'role' } });
  current.href = '/current';
  const silent = await request.get('/api/v1/restricted', { silent: true }).catch(cause => cause);
  expect(current.href).toBe('/current');
  expect(silent).toMatchObject({ status_code: 403, presentation: 'none' });
  expect(notices).not.toHaveBeenCalled();
});
it('runs the kicked-session interaction once and prevents a later HTTP401 from bypassing it', async () => {
  const { default: request, requestInterceptor } = await setup({ status_code: 10604, status_message: 'Session revoked' });
  const kicked = vi.fn();
  requestInterceptor.remoteLoginFuc = kicked;
  localStorage.setItem('ws_token', 'existing-session');
  const errors = await Promise.all([request.get('/one'), request.get('/two')].map(promise => promise.catch(cause => cause)));
  request.defaults.adapter = async config => { throw Object.assign(new Error('Unauthorized'), { config, response: { status: 401, data: {} } }); };
  const unauthorized = await request.get('/later').catch(cause => cause);
  expect(kicked).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem('ws_token')).toBe('existing-session');
  errors.forEach(error => expect(error).toMatchObject({ status_code: 10604, presentation: 'global' }));
  expect(unauthorized).toMatchObject({ httpStatus: 401, presentation: 'global' });
  expect(notices).not.toHaveBeenCalled();
});
it('keeps canceled requests identifiable without presenting a failure', async () => {
  const { default: request } = await setup({});
  request.defaults.adapter = async config => { throw Object.assign(new Error('Canceled'), { config, code: 'ERR_CANCELED' }); };
  await expect(request.get('/canceled')).rejects.toMatchObject({ kind: 'canceled', code: 'ERR_CANCELED', presentation: 'none' });
  expect(notices).not.toHaveBeenCalled();
});
