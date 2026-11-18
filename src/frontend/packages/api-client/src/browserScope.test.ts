import { expect, it, vi } from 'vitest';
import { BrowserScopeSession, needsBrowserScope, hasIndependentScope } from './browserScope';

// Any production dependency on the audit inventories makes this suite fail.
vi.mock('./requestScopeRoutes.json', () => { throw new Error('Audit inventory must not be imported at runtime'); });
vi.mock('./gatewayRequestScopeRoutes.json', () => { throw new Error('Gateway inventory must not be imported at runtime'); });

it.each(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])(
  'new same-origin browser endpoints inherit scope without a generated row: %s', method => {
    for (const path of ['/api/v1/dsh/admin/credit-settings', '/api/v1/dsh/admin/model-pricing',
      '/api/v1/future-feature/not-in-any-inventory', '/api/sensitive/dsh/settings',
      '/workspace/api/v1/future-feature/not-in-any-inventory'])
      expect(needsBrowserScope(method, path, 'http://localhost')).toBe(true);
  },
);

it('keeps session establishment and independent namespaces out of the bootstrap dependency', () => {
  for (const path of ['/api/v1/user/info', '/api/v1/user/login', '/api/v1/user/public_key',
    '/api/v1/user/sso', '/api/v1/user/switch-tenant', '/api/v1/env', '/api/v1/web/config',
    '/api/v1/tenants/3/status', '/api/v1/org-sync/configs', '/api/v1/settings',
    '/api/v1/user/profile/nickname', '/api/v1/departments/get_user_primary_department',
    '/api/v1/admin/request-scope', '/api/v1/admin/request-scope/bootstrap',
    '/api/v1/admin/tenant-scope', '/api/v1/dsh/browser-config', '/api/v1/dsh/token',
    '/api/v1/dsh/market/plugins', '/api/v2/workflow/invoke', '/api/oauth2/list',
    '/api/v1/public/workflow/one/run', '/assets/bisheng/config.js',
    'https://other.test/api/v1/future-feature', '//other.test/api/v1/future-feature'])
    expect(needsBrowserScope('POST', path, 'http://localhost')).toBe(false);
  expect(hasIndependentScope({'Share-Token': 'synthetic-link'})).toBe(true);
  expect(hasIndependentScope({'share-token': ''})).toBe(false);
  expect(needsBrowserScope('GET', '/api/v1/new', 'http://localhost', 'https://other.test/')).toBe(false);
  expect(needsBrowserScope('GET', '/api/v1/new', 'http://localhost', '/base/')).toBe(true);
  expect(needsBrowserScope('GET', 'http://localhost/base/api/v1/new', 'http://localhost', '/base/')).toBe(true);
});

it('one bootstrap admits concurrent requests and pauses on failure', async () => {
  const session = new BrowserScopeSession();
  const load = vi.fn().mockResolvedValue({ scope_tenant_id: 60 });
  await Promise.all([session.ensure(load), session.ensure(load)]);
  expect(load).toHaveBeenCalledTimes(1);
  session.reset();
  await expect(session.ensure(() => Promise.reject(new Error('unavailable')))).rejects.toThrow();
  await expect(session.ensure(load)).rejects.toMatchObject({status_code: 19705});
  expect(load).toHaveBeenCalledTimes(1);
});

it('an older bootstrap cannot overwrite an explicitly reconfirmed target', async () => {
  const session = new BrowserScopeSession();
  let resolve!: (value: {scope_tenant_id: number}) => void;
  const old = session.ensure(() => new Promise(ready => { resolve = ready; }));
  await Promise.resolve();
  session.pause();
  session.accept({scope_tenant_id: 65});
  resolve({scope_tenant_id: 60});
  await expect(old).rejects.toThrow('management_scope_changed');
  expect(session.tenant).toBe(65);
});

it('browser hints do not replace backend identity and credential admission', () => {
  expect(needsBrowserScope('POST', '/api/v1/chat/message', 'http://localhost')).toBe(true);
  expect(needsBrowserScope('GET', '/api/v1/knowledge/upload', 'http://localhost')).toBe(true);
  expect(needsBrowserScope('PUT', '/api/v1/dsh/admin/settings', 'http://localhost')).toBe(false);
});

it('recovers a pause only after one shared strict server confirmation', async () => {
  const session = new BrowserScopeSession();
  session.accept({scope_tenant_id: 60});
  session.pause();
  let resolve!: (proof: {scope_tenant_id: number}) => void;
  const load = vi.fn(() => new Promise<{scope_tenant_id: number}>(ready => { resolve = ready; }));
  const first = session.reconfirm(load);
  const second = session.reconfirm(load);
  await expect(session.ensure(load)).rejects.toMatchObject({status_code: 19705});
  expect(load).toHaveBeenCalledTimes(1);
  resolve({scope_tenant_id: 60});
  await Promise.all([first, second]);
  expect(session.tenant).toBe(60);
  expect(session.isPaused).toBe(false);
});

it.each([null, {scope_tenant_id: 0}, {scope_tenant_id: '60'}])('retains the pause after invalid confirmation %p', async proof => {
  const session = new BrowserScopeSession();
  session.accept({scope_tenant_id: 60});
  session.pause();
  await expect(session.reconfirm(async () => proof as never)).rejects.toBeTruthy();
  expect(session.tenant).toBeNull();
  expect(session.isPaused).toBe(true);
  await session.reconfirm(async () => ({scope_tenant_id: 60}));
  expect(session.tenant).toBe(60);
});

it('a failed confirmation remains retryable and never bootstraps Home', async () => {
  const session = new BrowserScopeSession();
  session.pause();
  await expect(session.reconfirm(async () => { throw new Error('selection expired'); })).rejects.toThrow('selection expired');
  expect(session.tenant).toBeNull();
  await session.reconfirm(async () => ({scope_tenant_id: 65}));
  expect(session.tenant).toBe(65);
});

it('does not resume while a switch is in progress', async () => {
  const session = new BrowserScopeSession();
  session.accept({scope_tenant_id: 60});
  const finish = session.beginSwitch();
  const load = vi.fn().mockResolvedValue({scope_tenant_id: 60});
  await expect(session.reconfirm(load)).rejects.toMatchObject({status_code: 19705});
  expect(load).not.toHaveBeenCalled();
  finish();
  finish();
  await session.reconfirm(load);
  expect(session.tenant).toBe(60);
});

it('does not rebind an old action when the server now selects another tenant', async () => {
  const session = new BrowserScopeSession();
  session.accept({scope_tenant_id: 60});
  session.pause();
  await expect(session.reconfirm(async () => ({scope_tenant_id: 65}))).rejects.toMatchObject({
    status_code: 19704, scopeReconfirmationChanged: true,
  });
  expect(session.tenant).toBeNull();
  expect(session.isPaused).toBe(true);
});

it.each([true, false])('late recovery cannot overwrite a newer confirmation, success=%s', async success => {
  const session = new BrowserScopeSession();
  session.accept({scope_tenant_id: 60});
  session.pause();
  let resolve!: (proof: {scope_tenant_id: number}) => void;
  let reject!: (error: Error) => void;
  const recovery = session.reconfirm(() => new Promise((yes, no) => {resolve = yes; reject = no;}));
  await Promise.resolve();
  session.accept({scope_tenant_id: 65});
  const rejected = expect(recovery).rejects.toBeTruthy();
  if (success) resolve({scope_tenant_id: 60}); else reject(new Error('late failure'));
  await rejected;
  expect(session.tenant).toBe(65);
  expect(session.isPaused).toBe(false);
});


it('only sends the management tenant for the two market list GETs', () => {
  const origin = 'http://localhost';
  const admin = '/api/v1/dsh/market/admin';
  for (const resource of ['plugins', 'workbenches']) {
    expect(needsBrowserScope('GET', `${admin}/${resource}?page=2`, origin)).toBe(true);
    expect(needsBrowserScope('GET', `${admin}/${resource}/record`, origin)).toBe(false);
    expect(needsBrowserScope('POST', `${admin}/${resource}`, origin)).toBe(false);
  }
  expect(needsBrowserScope('GET', '/api/v1/dsh/market/catalog', origin)).toBe(false);
  expect(needsBrowserScope('POST', `${admin}/imports`, origin)).toBe(false);
});
