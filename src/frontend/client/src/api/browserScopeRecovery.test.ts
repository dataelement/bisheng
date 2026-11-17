type RecordedRequest = {url?: string; method?: string; headers: {get: (name: string) => unknown; has: (name: string) => boolean}};

jest.mock('axios', () => {
  const actual = jest.requireActual('axios');
  const instance = actual.create();
  return {__esModule: true, ...actual, default: {...actual, create: () => instance}};
});
jest.mock('~/utils/loginRedirect', () => ({redirectToLogin: jest.fn()}));
jest.mock('i18next', () => ({__esModule: true, default: {exists: () => false, t: (key: string) => key}}));

async function transport() {
  const api = await import('./request');
  const instance = (jest.requireMock('axios') as {default: {create: () => {defaults: {adapter?: (config: RecordedRequest) => Promise<unknown>}}}}).default.create();
  const seen: RecordedRequest[] = [];
  let tenant = 60;
  let fail = false;
  let confirmationFails = false;
  instance.defaults.adapter = async config => {
    seen.push(config);
    const proof = config.url?.includes('/api/v1/admin/request-scope');
    return {config, status: 200, statusText: 'OK', headers: {}, data:
      (proof ? confirmationFails : fail)
        ? {status_code: 19705, status_message: 'management_scope_unavailable'}
        : {status_code: 200, data: proof ? {scope_tenant_id: tenant, source: 'own'} : {ok: true}}};
  };
  return {...api, seen, fail: (value: boolean) => {fail = value;},
    failConfirmation: (value: boolean) => {confirmationFails = value;},
    setTenant: (value: number) => {tenant = value;}};
}

beforeEach(() => {jest.resetModules();});

it('scopes new workbench endpoints and SSE preparation without an inventory row', async () => {
  const {default: request, seen, prepareBrowserHeaders} = await transport();
  await request.get('/api/v1/future-module/new-resource');
  expect(await prepareBrowserHeaders('POST', '/workspace/api/v1/future-module/stream')).toEqual({'X-Management-Tenant': '60'});
  expect(seen.filter(row => row.url?.endsWith('/bootstrap'))).toHaveLength(1);
  expect(seen.at(-1)?.headers.get('X-Management-Tenant')).toBe('60');
});

it('recovers a paused ordinary-user request through strict confirmation', async () => {
  const t = await transport();
  await t.default.get('/api/v1/future-module/new-resource');
  t.fail(true);
  await expect(t.default.get('/api/v1/future-module/new-resource')).rejects.toMatchObject({status_code: 19705});
  t.fail(false);
  await t.default.get('/api/v1/future-module/new-resource');
  expect(t.seen.filter(row => row.url === '/api/v1/admin/request-scope')).toHaveLength(1);
  expect(t.seen.filter(row => row.url?.endsWith('/bootstrap'))).toHaveLength(1);
});

it('recovers the old Gateway HTTP error shape without replaying the failed call automatically', async () => {
  const t = await transport();
  await t.default.get('/api/v1/future-module/new-resource');
  const instance = (jest.requireMock('axios') as {default: {create: () => {defaults: {
    adapter?: (config: RecordedRequest) => Promise<unknown>}}}}).default.create();
  let reads = 0;
  instance.defaults.adapter = async config => {
    if (config.url === '/api/v1/admin/request-scope') return {config, status: 200, headers: {},
      data: {status_code: 200, data: {scope_tenant_id: 60, source: 'own'}}};
    reads++;
    throw Object.assign(new Error('HTTP 400'), {config, response: {config, status: 400,
      data: {status_code: 19703, status_message: 'management scope required'}}});
  };
  await expect(t.default.get('/api/v1/future-module/new-resource')).rejects.toMatchObject({status_code: 19703});
  expect(await t.prepareBrowserHeaders('GET', '/api/v1/future-module/new-resource')).toEqual({'X-Management-Tenant': '60'});
  expect(reads).toBe(1);
});

it('retains the pause when confirmation fails, and permits a later successful retry', async () => {
  const t = await transport();
  await t.default.get('/api/v1/future-module/new-resource');
  t.fail(true);
  await expect(t.default.get('/api/v1/future-module/new-resource')).rejects.toBeTruthy();
  t.fail(false);
  t.failConfirmation(true);
  const before = t.seen.filter(row => row.url?.includes('future-module')).length;
  await expect(t.default.get('/api/v1/future-module/new-resource')).rejects.toBeTruthy();
  expect(t.seen.filter(row => row.url?.includes('future-module'))).toHaveLength(before);
  t.failConfirmation(false);
  await t.default.get('/api/v1/future-module/new-resource');
});

it('does not submit an old action after the server selects another tenant', async () => {
  const t = await transport();
  await t.default.get('/api/v1/future-module/new-resource');
  t.fail(true);
  await expect(t.default.get('/api/v1/future-module/new-resource')).rejects.toBeTruthy();
  t.fail(false);
  t.setTenant(65);
  const notify = jest.spyOn(window, 'dispatchEvent').mockReturnValue(true);
  await expect(t.default.post('/api/v1/future-module/new-resource', {})).rejects.toMatchObject({status_code: 19704});
  expect(t.seen.some(row => row.url?.includes('future-module') && row.method === 'post')).toBe(false);
  expect(notify).toHaveBeenCalledWith(expect.objectContaining({type: 'bisheng:management-scope-changed'}));
});

it('preserves independent public and shared-link requests without bootstrapping', async () => {
  const {default: request, prepareBrowserHeaders, seen} = await transport();
  for (const path of ['/api/v1/user/info', '/api/v1/dsh/browser-config', '/api/v1/dsh/token',
    '/api/v1/public/workflow/synthetic/run', '/api/v2/workflow/invoke',
    'https://external.example.invalid/api/v1/future-module']) await request.get(path);
  await request.get('/api/v1/linsight/task/1', {headers: {'share-token': 'synthetic-link'}});
  await request.post('/api/v1/apps/synthetic/versions/synthetic/preview?purpose=approval', {}, {managementContext: 'independent'});
  expect(await prepareBrowserHeaders('POST', '/api/v1/linsight/future', {'share-token': 'synthetic-link'})).toEqual({});
  expect(seen.some(row => row.url?.includes('/request-scope'))).toBe(false);
  expect(seen.every(row => !row.headers.has('X-Management-Tenant'))).toBe(true);
});
