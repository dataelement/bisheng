import { afterEach, describe, expect, it, vi } from 'vitest';
import { browserAuthEnvironment } from './authCoordination';
import { BrowserAuthSession } from './authSession';
import { AuthSessionError, type AuthEnvironment, type AuthSessionMetadata, type AuthTransport } from './authTypes';
const session = (id = 'a'.repeat(32), changes: Partial<AuthSessionMetadata> = {}): AuthSessionMetadata => ({
  session_id: id, access_expires_at: '2030-01-01T00:00:00Z',
  refresh_expires_at: '2030-03-01T00:00:00Z', session_expires_at: '2030-03-01T00:00:00Z',
  refresh_mode: 'cookie', delivery_state: 'BOUND', csrf_token: 'csrf', ...changes,
});
function fixture(transport: AuthTransport) {
  let selected: string | null = null;
  const environment: AuthEnvironment = { selectSession: vi.fn(value => { selected = value; }),
    selectedSession: () => selected, clearLegacyAuth: vi.fn(), publish: vi.fn(), subscribe: () => () => {},
    lock: async callback => callback(() => true), now: () => Date.parse('2029-01-01T00:00:00Z') };
  return { auth: new BrowserAuthSession(transport, environment), environment };
}
const ok = (data: unknown) => ({ status: 200, data: { status_code: 200, data } });
const failure = (code = 10651, status = 401) => ({ status,
  data: { status_code: code, data: { auth_reason: code === 10651 ? 'access_expired' : 'session_revoked', retryable: status === 503 } } });
describe('platform browser authentication', () => {
  it('binds gateway delivery before exposing a selected session', async () => {
    const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session(undefined, { delivery_state: 'PENDING_WEB_BIND' })))
      .mockResolvedValueOnce(ok(session()));
    const { auth, environment } = fixture(transport);
    await auth.initialize();
    expect(transport.mock.calls.map(call => call.slice(0, 2))).toEqual([
      ['GET', '/api/v1/auth/session'], ['POST', '/api/v1/auth/web-bootstrap']]);
    expect(environment.selectSession).toHaveBeenCalledExactlyOnceWith('a'.repeat(32), undefined);
  });
  it('coalesces expired Access recovery and obtains CSRF without valid Access', async () => {
    const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(failure()).mockResolvedValueOnce(ok({ csrf_token: 'recovery' }))
      .mockResolvedValueOnce(ok(session()));
    const { auth } = fixture(transport);
    const [first, second] = await Promise.all([auth.initialize(), auth.initialize()]);
    expect(first).toEqual(second);
    expect(transport.mock.calls).toHaveLength(3);
    expect(transport.mock.calls[2]).toEqual(['POST', '/api/v1/auth/refresh', {}, { 'X-CSRF-Token': 'recovery' }]);
  });
  it('does not issue empty refresh requests in host mode', async () => {
    const transport = vi.fn<AuthTransport>().mockResolvedValue(ok(session(undefined, { refresh_mode: 'host' })));
    const { auth } = fixture(transport);
    await auth.initialize();
    expect(await auth.refresh()).toBe(false);
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it('keeps the selected session on temporary service failures', async () => {
    const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session())).mockResolvedValueOnce(failure(10659, 503));
    const { auth, environment } = fixture(transport);
    await auth.initialize();
    await expect(auth.refresh(true)).rejects.toMatchObject({ retryable: true });
    expect(auth.snapshot?.session_id).toBe('a'.repeat(32));
    expect(environment.selectedSession()).toBe('a'.repeat(32));
  });
  it('clears only authentication markers on definitive legacy rejection', async () => {
    const { auth, environment } = fixture(vi.fn<AuthTransport>().mockResolvedValue(failure(10650)));
    expect(await auth.initialize()).toBeNull();
    expect(environment.clearLegacyAuth).toHaveBeenCalledOnce();
  });
  it('discards a late refresh result after logout', async () => {
    let finish: ((value: ReturnType<typeof ok>) => void) | undefined;
    const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session()))
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue(ok({}));
    const { auth, environment } = fixture(transport);
    await auth.initialize();
    const refresh = auth.refresh(true);
    await vi.waitFor(() => expect(finish).toBeDefined());
    const logout = auth.logout();
    finish?.(ok(session()));
    await Promise.all([refresh, logout]);
    expect(auth.snapshot).toBeNull();
    expect(environment.selectedSession()).toBeNull();
  });
  it('does not mistake invalid credentials for retryable failures', () => {
    expect(new AuthSessionError(401, 10653, 'revoked', false).retryable).toBe(false);
  });
});

it('recovers a stale CSRF token once without looping', async () => {
  const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session()))
    .mockResolvedValueOnce(ok(session())).mockResolvedValueOnce(failure(10660, 403)).mockResolvedValueOnce(ok({ csrf_token: 'new-csrf' }))
    .mockResolvedValueOnce(ok(session()));
  const { auth } = fixture(transport);
  await auth.initialize();
  expect(await auth.refresh(true)).toBe(true);
  expect(transport.mock.calls[4]?.[3]).toEqual({ 'X-CSRF-Token': 'new-csrf' });
});
it('logs out legacy DSH host bindings without sending platform refresh credentials', async () => {
  const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session(undefined, { refresh_mode: 'host', auth_source: 'legacy_dsh' })))
    .mockResolvedValueOnce(ok({}));
  const { auth } = fixture(transport);
  await auth.initialize();
  await auth.logout();
  expect(transport.mock.calls[1]?.slice(0, 2)).toEqual(['POST', '/api/v1/user/logout']);
});
it('logs out a platform host child using Access and CSRF without touching native Refresh', async () => {
  const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session(undefined, { refresh_mode: 'host' })))
    .mockResolvedValueOnce(ok({}));
  const { auth } = fixture(transport);
  await auth.initialize();
  await auth.logout();
  expect(transport.mock.calls[1]).toEqual(['POST', '/api/v1/auth/logout', {}, { 'X-CSRF-Token': 'csrf' }]);
});
it('keeps credentials out of cross-tab notifications', async () => {
  const { auth, environment } = fixture(vi.fn<AuthTransport>().mockResolvedValue(ok(session())));
  await auth.login({ user_name: 'person', password: 'encrypted' });
  expect(environment.publish).toHaveBeenCalledWith({ type: 'login', session: 'a'.repeat(32) });
});

it('rechecks metadata after the cross-tab lock and rotates only once', async () => {
  let serverSession = session();
  const transport = vi.fn<AuthTransport>().mockImplementation(async (_method, path) => {
    if (path.endsWith('/refresh')) serverSession = session(undefined, { access_expires_at: '2030-01-02T00:00:00Z' });
    return ok(serverSession);
  });
  const { environment } = fixture(transport);
  let pending = Promise.resolve();
  environment.lock = callback => {
    const task = pending.then(() => callback(() => true));
    pending = task.then(() => undefined, () => undefined);
    return task;
  };
  const first = new BrowserAuthSession(transport, environment);
  const second = new BrowserAuthSession(transport, environment);
  await Promise.all([first.initialize(), second.initialize()]);
  await Promise.all([first.refresh(true), second.refresh(true)]);
  expect(transport.mock.calls.filter(call => call[1].endsWith('/refresh'))).toHaveLength(1);
});
it('cannot select an old sid after a missed account-switch notification', async () => {
  let finish: ((value: ReturnType<typeof ok>) => void) | undefined;
  const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session()))
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const { auth, environment } = fixture(transport);
  await auth.initialize();
  const refresh = auth.refresh();
  await vi.waitFor(() => expect(finish).toBeDefined());
  environment.selectSession('b'.repeat(32));
  finish?.(ok(session()));
  expect(await refresh).toBe(false);
  expect(environment.selectedSession()).toBe('b'.repeat(32));
});
it('does not clear a new selector when an old request is rejected after a missed notification', async () => {
  let finish: ((value: ReturnType<typeof failure>) => void) | undefined;
  const transport = vi.fn<AuthTransport>().mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const { auth, environment } = fixture(transport);
  environment.selectSession('a'.repeat(32));
  const initialize = auth.initialize();
  await vi.waitFor(() => expect(finish).toBeDefined());
  environment.selectSession('b'.repeat(32));
  finish?.(failure(10655));
  await initialize;
  expect(environment.selectedSession()).toBe('b'.repeat(32));
});
it('clears the local selector before remote logout and transmits only a non-secret selector header', async () => {
  const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session()));
  const { auth, environment } = fixture(transport);
  await auth.initialize();
  transport.mockImplementationOnce(async (_method, _path, body, headers) => {
    expect(environment.selectedSession()).toBeNull();
    expect(body).toEqual({});
    expect(headers).toEqual({ 'X-CSRF-Token': 'csrf', 'X-Platform-Session': 'a'.repeat(32) });
    return ok({});
  });
  await auth.logout();
});
it('keeps local logout complete when the server cannot confirm revocation', async () => {
  const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session())).mockRejectedValueOnce(new Error('offline'));
  const { auth, environment } = fixture(transport);
  await auth.initialize();
  await expect(auth.logout()).rejects.toMatchObject({ retryable: true });
  expect(auth.snapshot).toBeNull();
  expect(environment.selectedSession()).toBeNull();
});
it.each([10650, 10651])('recovers a cold mobile WebView without its expired Access cookie (%s)', async code => {
  const transport = vi.fn<AuthTransport>().mockResolvedValue(failure(code));
  const { auth, environment } = fixture(transport);
  environment.selectSession('a'.repeat(32));
  environment.hostOwned = () => true;
  environment.requestHostRenewal = vi.fn();
  expect(auth.snapshot).toBeNull();
  expect(await auth.initialize()).toBeNull();
  expect(auth.hostPending).toBe(true);
  expect(environment.selectedSession()).toBe('a'.repeat(32));
  expect(environment.requestHostRenewal).toHaveBeenCalledOnce();
  expect(environment.clearLegacyAuth).not.toHaveBeenCalled();
  expect(transport.mock.calls).toEqual([['GET', '/api/v1/auth/session', undefined, undefined]]);
  expect(await auth.refresh()).toBe(false);
  expect(transport).toHaveBeenCalledOnce();
});

it('detects the real mobile bridge and preserved hint when rebuilding the browser controller without Access', async () => {
  const postMessage = vi.fn();
  const host = Object.assign(new EventTarget(), { BishengMobile: { postMessage } });
  vi.stubGlobal('window', host);
  vi.stubGlobal('document', { cookie: `platform_session_hint=${'a'.repeat(32)}` });
  vi.stubGlobal('location', { protocol: 'https:' });
  vi.stubGlobal('BroadcastChannel', undefined);
  const environment = browserAuthEnvironment();
  environment.lock = async callback => callback(() => true);
  const transport = vi.fn<AuthTransport>().mockResolvedValue(failure(10650));
  const auth = new BrowserAuthSession(transport, environment);
  await auth.initialize();
  expect(postMessage).toHaveBeenCalledWith('{"type":"platform_auth_refresh_required"}');
  expect(auth.hostPending).toBe(true);
  expect(environment.selectedSession()).toBe('a'.repeat(32));
  expect(transport.mock.calls.map(call => call[1])).toEqual(['/api/v1/auth/session']);
  auth.dispose();
});
it('accepts replacement host credentials after a cold start without attempting cookie refresh', async () => {
  const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(failure(10650))
    .mockResolvedValueOnce(ok(session(undefined, { refresh_mode: 'host' })));
  const { auth, environment } = fixture(transport);
  environment.selectSession('a'.repeat(32));
  environment.hostOwned = () => true;
  environment.requestHostRenewal = vi.fn();
  await auth.initialize();
  expect(auth.hostPending).toBe(true);
  expect(auth.snapshot).toBeNull();
  expect(await auth.initialize(true)).toMatchObject({ refresh_mode: 'host' });
  expect(auth.hostPending).toBe(false);
  expect(transport.mock.calls.map(call => call.slice(0, 2))).toEqual([
    ['GET', '/api/v1/auth/session'], ['GET', '/api/v1/auth/session'],
  ]);
  expect(environment.clearLegacyAuth).not.toHaveBeenCalled();
});
afterEach(() => { vi.unstubAllGlobals(); });
it('broadcasts a gateway account switch after binding so other SPA tabs reload identity', async () => {
  const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session(undefined, { delivery_state: 'PENDING_WEB_BIND' })))
    .mockResolvedValueOnce(ok(session()));
  const { auth, environment } = fixture(transport);
  await auth.initialize();
  expect(environment.publish).toHaveBeenCalledWith({ type: 'login', session: 'a'.repeat(32) });
});
it('recovers an already-rotated binding only with its existing selected Refresh cookie', async () => {
  const transport = vi.fn<AuthTransport>().mockResolvedValueOnce(ok(session(undefined, { delivery_state: 'PENDING_WEB_BIND' })))
    .mockResolvedValueOnce(failure(10664, 409)).mockResolvedValueOnce(ok({ csrf_token: 'existing-refresh' }))
    .mockResolvedValueOnce(ok(session()));
  const { auth, environment } = fixture(transport);
  environment.selectSession('a'.repeat(32));
  expect(await auth.initialize()).toMatchObject({ delivery_state: 'BOUND' });
  expect(transport.mock.calls.at(-1)).toEqual(['POST', '/api/v1/auth/refresh', {}, { 'X-CSRF-Token': 'existing-refresh' }]);
});

it.each([10454400, 13046400])('passes the frozen server cookie retention to the browser selector (%s seconds)', async retention => {
  const transport = vi.fn<AuthTransport>().mockResolvedValue(ok(Object.assign(session(), { cookie_retention_seconds: retention })));
  const { auth, environment } = fixture(transport);
  await auth.initialize();
  expect(environment.selectSession).toHaveBeenCalledExactlyOnceWith('a'.repeat(32), retention);
});
it.each([undefined, 10454400, 13046400])('writes the matching hint Max-Age for default and custom cookie retention (%s)', retention => {
  vi.stubGlobal('window', new EventTarget());
  vi.stubGlobal('document', { cookie: '' });
  vi.stubGlobal('location', { protocol: 'https:' });
  vi.stubGlobal('BroadcastChannel', undefined);
  const environment = browserAuthEnvironment();
  environment.selectSession('a'.repeat(32), retention);
  expect(document.cookie).toContain(`Max-Age=${retention ?? 10454400}`);
  expect(document.cookie).toContain('; Secure');
  environment.selectSession(null, retention);
  expect(document.cookie).toContain('Max-Age=0');
});
