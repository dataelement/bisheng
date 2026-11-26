import { expect, it, vi } from 'vitest';
import request from '@/controllers/request';
import { listProviderInstances, updateProviderInstance } from '@/controllers/API/providerInstances';

vi.mock('@/controllers/request', () => ({ default: { get: vi.fn(), patch: vi.fn() } }));
const row = {
  id: 3,
  endpoint: 'http://192.168.1.2:18080',
  remote_scope_id: '10000',
  state: 'ready',
  capability_revision: 1,
  has_api_key: true,
  has_upload_signed_token_secret: false,
};

it('reads and writes the connection without an extract template field', async () => {
  vi.mocked(request.get).mockResolvedValueOnce([row, { ...row, id: 4 }]);
  expect((await listProviderInstances()).map(r => r.id)).toEqual([3, 4]);
  vi.mocked(request.patch).mockResolvedValueOnce(row);
  const input = { endpoint: row.endpoint, remote_scope_id: '10000' };
  await updateProviderInstance(3, input);
  expect(request.patch).toHaveBeenCalledWith('/api/v1/knowledge/provider-instances/3', input);
});

it('refuses a row whose endpoint is not a string', async () => {
  vi.mocked(request.get).mockResolvedValueOnce([{ ...row, endpoint: 7 }]);
  await expect(listProviderInstances()).rejects.toThrow();
});
