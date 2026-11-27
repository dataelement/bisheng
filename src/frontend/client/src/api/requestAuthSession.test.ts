import { AuthSessionError } from '@bisheng/api-client';
import request, { platformAuth } from './request';
jest.mock('axios', () => {
  const actual = jest.requireActual<typeof import('axios')>('axios');
  const instance = actual.create();
  return { __esModule: true, ...actual, default: { ...actual, create: () => instance } };
});
jest.mock('~/utils/loginRedirect', () => ({ redirectToLogin: jest.fn() }));
jest.mock('i18next', () => ({ __esModule: true, default: { exists: () => false, t: (key: string) => key } }));
const transport = (jest.requireMock('axios') as typeof import('axios')).default.create();
const adapter = transport.defaults.adapter;
afterEach(() => { transport.defaults.adapter = adapter; jest.restoreAllMocks(); delete (window as unknown as Record<string, unknown>).BishengMobile; });
const metadata = { session_id: 'a'.repeat(32), access_expires_at: '2030-01-01T00:00:00Z',
  refresh_expires_at: '2030-03-01T00:00:00Z', session_expires_at: '2030-03-01T00:00:00Z',
  refresh_mode: 'cookie' as const, delivery_state: 'BOUND' as const, csrf_token: 'csrf' };
it.each([200, 401])('recovers Access expiry with HTTP %s through one shared refresh and one retry', async status => {
  const refresh = jest.spyOn(platformAuth, 'refresh').mockResolvedValue(true);
  let calls = 0;
  transport.defaults.adapter = async config => {
    if (++calls > 1) return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: { ok: true } } };
    const response = { config, status, statusText: 'Expired', headers: {}, data: { status_code: 10651 } };
    if (status === 401) throw Object.assign(new Error('Expired'), { config, response });
    return response;
  };
  expect(await request.get('/test')).toMatchObject({ data: { ok: true } });
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(calls).toBe(2);
});
it('retains authentication when refresh returns a real HTTP 503', async () => {
  platformAuth.snapshot = metadata;
  jest.spyOn(platformAuth, 'refresh').mockRejectedValue(new AuthSessionError(503, 10659, 'auth_service_unavailable', true));
  transport.defaults.adapter = async config => { throw Object.assign(new Error('Expired'), { config,
    response: { config, status: 401, data: { status_code: 10651 } } }); };
  await expect(request.get('/test')).rejects.toMatchObject({ status: 503, retryable: true });
  expect(platformAuth.snapshot).toEqual(metadata);
});
it('asks the mobile host to reconnect without an empty Refresh or login redirect', async () => {
  const postMessage = jest.fn();
  Object.assign(window, { BishengMobile: { postMessage } });
  platformAuth.snapshot = { ...metadata, refresh_mode: 'host' };
  const refresh = jest.spyOn(platformAuth, 'refresh');
  transport.defaults.adapter = async config => { throw Object.assign(new Error('Expired'), { config,
    response: { config, status: 401, data: { status_code: 10651 } } }); };
  await expect(request.get('/test')).rejects.toBeDefined();
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(postMessage).toHaveBeenCalledWith('{"type":"platform_auth_refresh_required"}');
  expect(jest.requireMock('~/utils/loginRedirect').redirectToLogin).not.toHaveBeenCalled();
});
it('does not inject management context into credential-owned auth requests', async () => {
  transport.defaults.adapter = async config => {
    expect(config.headers.has('X-Management-Tenant')).toBe(false);
    return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: { csrf_token: 'csrf' } } };
  };
  expect(await request.get('/api/v1/auth/csrf')).toMatchObject({ data: { csrf_token: 'csrf' } });
});
it('uses the canonical root authentication path so the workspace base cannot exclude Refresh cookies', async () => {
  const previousBase = transport.defaults.baseURL;
  const previousLocks = navigator.locks;
  Object.defineProperty(navigator, 'locks', { configurable: true, value: {
    request: (_name: unknown, _options: unknown, callback: () => unknown) => callback(),
  } });
  transport.defaults.baseURL = '/workspace/';
  transport.defaults.adapter = async config => {
    expect(config.url).toBe('/api/v1/auth/session');
    expect(config.baseURL).toBe(window.location.origin);
    expect(config.headers.has('X-Management-Tenant')).toBe(false);
    return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: metadata } };
  };
  try { await expect(platformAuth.initialize(true)).resolves.toMatchObject({ session_id: metadata.session_id }); }
  finally {
    transport.defaults.baseURL = previousBase;
    Object.defineProperty(navigator, 'locks', { configurable: true, value: previousLocks });
  }
});
