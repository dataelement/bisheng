import { expect, it, vi } from 'vitest';

// Capture the exact config each verb hands to the transport so the scope header
// contract is asserted on the wrapper itself, not on a caller's assumptions.
const seen = vi.hoisted(() => ({ calls: [] as Array<{ verb: string; config: Record<string, unknown> }> }));

vi.mock('axios', () => {
  const verb = (name: string) => async (url: string, _data?: unknown, config?: Record<string, unknown>) => {
    seen.calls.push({ verb: name, config: { ...(config ?? {}), url } });
    return { data: { status_code: 200, data: {} }, headers: {}, status: 200, config: { url } };
  };
  const instance = {
    defaults: { baseURL: '/' },
    interceptors: { request: { use: () => undefined }, response: { use: () => undefined } },
    get: verb('get'),
    post: verb('post'),
    put: verb('put'),
    patch: verb('patch'),
    delete: verb('delete'),
  };
  const axios = { create: () => instance, get: verb('get'), post: verb('post'), defaults: {} };
  return { __esModule: true, default: axios, ...axios };
});

vi.mock('~/utils/loginRedirect', () => ({ redirectToLogin: vi.fn() }));

const headersOf = (config: Record<string, unknown>) =>
  Object.fromEntries(
    Object.entries((config.headers ?? {}) as Record<string, unknown>).map(([key, value]) => [key.toLowerCase(), value]),
  );

it.each(['put', 'patch'] as const)('keeps the caller scope header on %s beside the JSON content type', async verb => {
  const request = (await import('~/api/request')).default;
  await request[verb]('/api/v1/scope-contract', { a: 1 }, {
    headers: { 'X-Management-Tenant': '60' },
    managementContext: 'independent',
  });
  const call = seen.calls.at(-1);
  expect(call?.verb).toBe(verb);
  // Replacing `headers` with only Content-Type silently dropped the tenant pin; a
  // global super admin then got a 400 that no endpoint logged.
  expect(headersOf(call!.config)['x-management-tenant']).toBe('60');
  expect(String(headersOf(call!.config)['content-type'])).toContain('application/json');
});
