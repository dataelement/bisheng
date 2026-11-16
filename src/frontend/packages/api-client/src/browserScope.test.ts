import { expect, it, vi } from 'vitest';
import { BrowserScopeSession, needsBrowserScope, requestScopeKind } from './browserScope';

it('uses the registered routes for reads and writes without leaking to other origins', () => {
  expect(needsBrowserScope('GET', '/api/v1/guest-link/workflow/a', 'http://localhost')).toBe(true);
  expect(needsBrowserScope('GET', '/api/v1/user/info', 'http://localhost')).toBe(false);
  expect(needsBrowserScope('PATCH', '/api/v1/user/profile/nickname', 'http://localhost')).toBe(false);
  expect(needsBrowserScope('GET', '/api/v1/departments/get_user_primary_department', 'http://localhost')).toBe(false);
  expect(needsBrowserScope('POST', '/api/v1/user/create', 'http://localhost')).toBe(true);
  expect(needsBrowserScope('POST', '/api/v2/workflow/invoke', 'http://localhost')).toBe(false);
  expect(requestScopeKind('GET', 'https://other.test/api/v1/llm/workbench', 'http://localhost')).toBeNull();
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
