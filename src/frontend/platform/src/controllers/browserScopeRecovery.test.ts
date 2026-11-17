type RecordedRequest = {url?: string; method?: string; headers: {get: (name: string) => unknown; has: (name: string) => boolean}};
import { beforeEach, afterEach, expect, it, vi } from 'vitest';

vi.mock('@bisheng/ui', () => ({ notification: { open: vi.fn() } }));
vi.mock('i18next', () => ({ default: { exists: () => false, t: (key: string) => key } }));

beforeEach(() => { vi.resetModules(); });
afterEach(() => { vi.restoreAllMocks(); });

async function transport() {
  const request = (await import('./request')).default;
  const seen: RecordedRequest[] = [];
  let tenant = 60;
  let failBusiness = false;
  let failConfirmation = false;
  request.defaults.adapter = async config => {
    seen.push(config);
    const proof = config.url?.startsWith('/api/v1/admin/request-scope');
    const failed = proof ? failConfirmation : failBusiness;
    return {
      config, status: 200, statusText: 'OK', headers: {},
      data: failed
        ? {status_code: 19705, status_message: 'management_scope_unavailable'}
        : {status_code: 200, data: proof ? {scope_tenant_id: tenant, source: 'selected'} : {ok: true}},
    };
  };
  return {request, seen, setTenant: (value: number) => { tenant = value; },
    failBusiness: (value: boolean) => { failBusiness = value; },
    failConfirmation: (value: boolean) => { failConfirmation = value; }};
}

it('new credit APIs and a never-enumerated endpoint carry scope before navigating to knowledge', async () => {
  const {request, seen} = await transport();
  for (const path of ['/api/v1/dsh/admin/credit-settings', '/api/v1/dsh/admin/model-pricing',
    '/api/v1/future-module/new-resource', '/api/v1/knowledge/space/mine']) {
    await request.get(path, {silent: true});
  }
  expect(seen.filter(row => row.url?.endsWith('/bootstrap'))).toHaveLength(1);
  for (const config of seen.filter(row => !row.url?.includes('/request-scope')))
    expect(config.headers.get('X-Management-Tenant')).toBe('60');
});

it('the actual admin hook API recovers a silent failure with strict GET, not a Home bootstrap', async () => {
  const t = await transport();
  await t.request.get('/api/v1/dsh/admin/credit-settings');
  t.failBusiness(true);
  await expect(t.request.get('/api/v1/dsh/admin/credit-settings', {silent: true})).rejects.toMatchObject({status_code: 19705});
  t.failBusiness(false);
  const {getTenantScope} = await import('./API/admin');
  expect((await getTenantScope()).scope_tenant_id).toBe(60);
  await t.request.get('/api/v1/knowledge/space/mine');
  expect(t.seen.filter(row => row.url === '/api/v1/admin/request-scope').map(row => row.method)).toEqual(['get']);
  expect(t.seen.filter(row => row.url?.endsWith('/bootstrap'))).toHaveLength(1);
});

it('recovers the HTTP 400 / 19703 shape observed on 116 without changing the selected tenant', async () => {
  const {request} = await transport();
  await request.get('/api/v1/dsh/admin/credit-settings');
  const seen: string[] = [];
  request.defaults.adapter = async config => {
    seen.push(`${config.method}:${config.url}`);
    if (config.url === '/api/v1/admin/request-scope') return {config, status: 200, statusText: 'OK', headers: {},
      data: {status_code: 200, data: {scope_tenant_id: 60}}};
    throw Object.assign(new Error('HTTP 400'), {config, response: {config, status: 400,
      data: {status_code: 19703, status_message: 'Select a management tenant'}}});
  };
  await expect(request.get('/api/v1/dsh/admin/credit-settings', {silent: true})).rejects.toMatchObject({status_code: 19703});
  const {getTenantScope} = await import('./API/admin');
  expect((await getTenantScope()).scope_tenant_id).toBe(60);
  expect(seen).toEqual(['get:/api/v1/dsh/admin/credit-settings', 'get:/api/v1/admin/request-scope']);
});

it('releases the switch barrier and confirms the actual selection even when the switch response fails', async () => {
  const {request} = await transport();
  await request.get('/api/v1/future-module/new-resource');
  const notify = vi.spyOn(window, 'dispatchEvent').mockReturnValue(true);
  request.defaults.adapter = async config => {
    if (config.url === '/api/v1/admin/tenant-scope') throw Object.assign(new Error('Audit failed after selection changed'), {config});
    return {config, status: 200, statusText: 'OK', headers: {}, data: {status_code: 200,
      data: config.url === '/api/v1/admin/request-scope' ? {scope_tenant_id: 65} : {ok: true}}};
  };
  const {setTenantScope} = await import('./API/admin');
  await expect(setTenantScope(65)).rejects.toBeTruthy();
  const {managementRequestScope} = await import('./managementScope');
  expect(managementRequestScope()).toBe(65);
  expect(notify).toHaveBeenCalledWith(expect.objectContaining({type: 'bisheng:management-scope-changed'}));
  await request.get('/api/v1/future-module/new-resource');
});

it('a failed confirmation sends no business request and a later retry can recover', async () => {
  const t = await transport();
  await t.request.get('/api/v1/dsh/admin/credit-settings');
  const {pauseManagementScope, managementRequestScope} = await import('./managementScope');
  pauseManagementScope();
  t.failConfirmation(true);
  const before = t.seen.filter(row => !row.url?.includes('/request-scope')).length;
  await expect(t.request.get('/api/v1/knowledge/space/mine', {silent: true})).rejects.toMatchObject({status_code: 19705});
  expect(managementRequestScope()).toBeNull();
  expect(t.seen.filter(row => !row.url?.includes('/request-scope'))).toHaveLength(before);
  t.failConfirmation(false);
  await t.request.get('/api/v1/knowledge/space/mine');
  expect(managementRequestScope()).toBe(60);
});

it('never submits an old mutation to another tenant after reconfirmation', async () => {
  const t = await transport();
  await t.request.get('/api/v1/future-module/new-resource');
  const {pauseManagementScope} = await import('./managementScope');
  pauseManagementScope();
  t.setTenant(65);
  const notify = vi.spyOn(window, 'dispatchEvent').mockReturnValue(true);
  await expect(t.request.post('/api/v1/future-module/new-resource', {})).rejects.toMatchObject({status_code: 19704});
  expect(t.seen.filter(row => row.url === '/api/v1/future-module/new-resource' && row.method === 'post')).toHaveLength(0);
  expect(notify).toHaveBeenCalledWith(expect.objectContaining({type: 'bisheng:management-scope-changed'}));
});

it('blocks recovery during a switch and discards late responses without pausing the newer target', async () => {
  const t = await transport();
  await t.request.get('/api/v1/future-module/new-resource');
  const {beginManagementScopeSwitch, acceptManagementScope, managementRequestScope} = await import('./managementScope');
  const finish = beginManagementScopeSwitch();
  const before = t.seen.length;
  await expect(t.request.get('/api/v1/future-module/new-resource')).rejects.toMatchObject({status_code: 19705});
  expect(t.seen).toHaveLength(before);
  acceptManagementScope(65);
  finish();
  const {handleRequestResponse, handleRequestError} = await import('./request');
  const config = {url: '/api/v1/future-module/new-resource', method: 'get', managementScopeSnapshot: 60};
  await expect(handleRequestResponse({config, headers: {}, status: 200,
    data: {status_code: 200, data: {old: true}}})).rejects.toMatchObject({status_code: 19704});
  await expect(handleRequestError({config, response: {status: 409,
    data: {status_code: 19704, status_message: 'old'}}})).rejects.toBeTruthy();
  expect(managementRequestScope()).toBe(65);
});

it('keeps login, independent credentials and external requests free of scope bootstrap', async () => {
  const {request, seen} = await transport();
  for (const path of ['/api/v1/user/info', '/api/v1/user/login', '/api/v1/dsh/browser-config',
    '/api/v2/workflow/invoke', '/api/v1/public/workflow/synthetic/run',
    'https://external.example.invalid/api/v1/future-module']) {
    await request.get(path);
  }
  await request.get('/api/v1/linsight/task/1', {headers: {'share-token': 'synthetic-link'}});
  expect(seen.some(row => row.url?.includes('/request-scope'))).toBe(false);
  expect(seen.every(row => !row.headers.has('X-Management-Tenant'))).toBe(true);
});

it('leaves identity and platform administration reachable while business scope is paused', async () => {
  const {request, seen} = await transport();
  const {pauseManagementScope} = await import('./managementScope');
  pauseManagementScope();
  for (const path of ['/api/v1/tenants/', '/api/v1/dsh/admin/settings', '/api/v1/user/info',
    '/api/v1/user/profile/nickname', '/api/v1/org-sync/configs']) await request.get(path);
  expect(seen.some(row => row.url?.includes('/request-scope'))).toBe(false);
  expect(seen.every(row => !row.headers.has('X-Management-Tenant'))).toBe(true);
});
