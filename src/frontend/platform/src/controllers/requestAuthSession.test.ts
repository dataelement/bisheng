import { beforeEach, afterEach, expect, it, vi } from 'vitest';
vi.mock('@bisheng/ui', () => ({ notification: { open: vi.fn() } }));
vi.mock('i18next', () => ({ default: { exists: () => false, t: (key: string) => key } }));
beforeEach(() => {
  vi.resetModules();
  const values = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) });
  vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: vi.fn(), removeItem: vi.fn() });
  vi.stubGlobal('navigator', { locks: { request: (_name: unknown, _options: unknown, callback: () => unknown) => callback() } });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const metadata = { session_id: 'a'.repeat(32), access_expires_at: '2030-01-01T00:00:00Z',
  refresh_expires_at: '2030-03-01T00:00:00Z', session_expires_at: '2030-03-01T00:00:00Z',
  refresh_mode: 'cookie' as const, delivery_state: 'BOUND' as const, csrf_token: 'csrf' };
it('routes web login through the shared cookie API without tenant headers or raw credentials', async () => {
  const { default: request, platformAuth } = await import('./request');
  const calls: string[] = [];
  request.defaults.baseURL = '/custom/';
  request.defaults.adapter = async config => {
    calls.push(config.url || '');
    if (config.url?.includes('/auth/')) {
      expect(config.headers.has('X-Management-Tenant')).toBe(false);
      expect(config.baseURL).toBe(window.location.origin);
    }
    return { config, status: 200, statusText: 'OK', headers: {},
      data: { status_code: 200, data: config.url?.endsWith('/login') ? metadata : { user_id: 1 } } };
  };
  localStorage.setItem('theme', 'dark');
  const { loginApi } = await import('./API/user');
  expect(await loginApi('person', 'encrypted')).toMatchObject({ user_id: 1 });
  expect(calls).toEqual(['/api/v1/auth/login', '/api/v1/user/info']);
  expect(localStorage.getItem('ws_token')).toBeNull();
  expect(localStorage.getItem('theme')).toBe('dark');
  platformAuth.dispose();
});
it('retries an expired business request once after the shared refresh', async () => {
  const { default: request, platformAuth } = await import('./request');
  const refresh = vi.spyOn(platformAuth, 'refresh').mockResolvedValue(true);
  let count = 0;
  request.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {},
    data: ++count === 1 ? { status_code: 10651 } : { status_code: 200, data: { ok: true } } });
  expect(await request.get('/test')).toEqual({ ok: true });
  expect(refresh).toHaveBeenCalledOnce();
  expect(count).toBe(2);
  platformAuth.dispose();
});
it('does not refresh or redirect host-owned sessions with an empty credential', async () => {
  const { default: request, platformAuth } = await import('./request');
  platformAuth.snapshot = { ...metadata, refresh_mode: 'host' };
  const refresh = vi.spyOn(platformAuth, 'refresh');
  request.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 10651 } });
  await expect(request.get('/test')).rejects.toMatchObject({ reason: 'host_refresh_required' });
  expect(refresh).toHaveBeenCalledOnce();
  platformAuth.dispose();
});
it('keeps the selected session when refresh is temporarily unavailable', async () => {
  const { AuthSessionError } = await import('@bisheng/api-client');
  const { default: request, platformAuth } = await import('./request');
  platformAuth.snapshot = metadata as typeof platformAuth.snapshot;
  vi.spyOn(platformAuth, 'refresh').mockRejectedValue(new AuthSessionError(503, 10659, 'auth_service_unavailable', true));
  request.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 10651 } });
  await expect(request.get('/test')).rejects.toMatchObject({ retryable: true });
  expect(platformAuth.snapshot).toEqual(metadata);
  platformAuth.dispose();
});

it('retries real HTTP 401 expiry and keeps the original transport configuration', async () => {
  const { default: request, platformAuth } = await import('./request');
  const refresh = vi.spyOn(platformAuth, 'refresh').mockResolvedValue(true);
  let count = 0;
  request.defaults.adapter = async config => {
    if (++count === 1) throw Object.assign(new Error('Expired'), { config, response: { config, status: 401, data: { status_code: 10651 } } });
    expect(config.headers.get('X-Test')).toBe('preserved');
    return { config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 200, data: { ok: true } } };
  };
  expect(await request.get('/test', { headers: { 'X-Test': 'preserved' } })).toEqual({ ok: true });
  expect(refresh).toHaveBeenCalledOnce();
  expect(count).toBe(2);
  platformAuth.dispose();
});
it('does not retry a real HTTP 503 authentication failure as a password failure', async () => {
  const { AuthSessionError } = await import('@bisheng/api-client');
  const { default: request, platformAuth } = await import('./request');
  platformAuth.snapshot = metadata as typeof platformAuth.snapshot;
  vi.spyOn(platformAuth, 'refresh').mockRejectedValue(new AuthSessionError(503, 10659, 'auth_service_unavailable', true));
  request.defaults.adapter = async config => { throw Object.assign(new Error('Expired'), { config, response: { config, status: 401, data: { status_code: 10651 } } }); };
  await expect(request.get('/test')).rejects.toMatchObject({ status: 503, retryable: true });
  expect(platformAuth.snapshot).toEqual(metadata);
  platformAuth.dispose();
});
