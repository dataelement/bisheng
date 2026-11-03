import { ApiError } from '@bisheng/api-client';
import { uploadFileToServerApi } from './knowledge';
import request from './request';

jest.mock('axios', () => {
  const actual = jest.requireActual('axios');
  const instance = actual.create();
  return { __esModule: true, ...actual, default: { ...actual, create: () => instance } };
});
jest.mock('~/api/chat/headers-helpers', () => ({ setTokenHeader: jest.fn() }));
jest.mock('~/utils/loginRedirect', () => ({ redirectToLogin: jest.fn() }));

const transport = jest.requireMock('axios').default.create();
const mockCalls: { url?: string; tenant?: string; body: unknown }[] = [];
let scopeStatus: number;
let uploadStatus: number;
let scopeHeader: string | undefined;
beforeEach(() => {
  mockCalls.length = 0;
  scopeStatus = 200;
  uploadStatus = 200;
  scopeHeader = '3';
  transport.defaults.adapter = async (config: { url?: string; headers: Record<string, string>; data: unknown }) => {
    mockCalls.push({ url: config.url, tenant: config.headers['X-Management-Tenant'], body: config.data });
    const reading = config.url?.endsWith('/info');
    return { config, status: 200, statusText: 'OK',
      headers: reading && scopeHeader !== undefined ? { 'x-management-tenant': scopeHeader } : {},
      data: reading
        ? { status_code: scopeStatus, data: { id: 4322 } }
        : { status_code: uploadStatus, data: { file_path: '/tmp/notes.txt' } },
    };
  };
});

it('pins upload to the server-confirmed tenant without requiring a tenant picker', async () => {
  await uploadFileToServerApi('4322', new File(['notes'], 'notes.txt'));
  expect(mockCalls.map(call => call.url)).toEqual(['/api/v1/knowledge/space/4322/info', '/api/v1/knowledge/upload/4322']);
  expect(mockCalls[1].tenant).toBe('3');
});

it('preserves the explicit filename when uploading a folder entry', async () => {
  await uploadFileToServerApi('4322', new File(['notes'], 'Folder/notes.txt'), 'notes.txt');
  const uploaded = mockCalls[mockCalls.length - 1]?.body as FormData;
  expect((uploaded.get('file') as File).name).toBe('notes.txt');
});

it('does not upload if reading the target space fails', async () => {
  scopeStatus = 10901;
  await expect(uploadFileToServerApi('4322', new File(['notes'], 'notes.txt'))).rejects.toBeInstanceOf(ApiError);
  expect(mockCalls).toHaveLength(1);
  expect(mockCalls[0].url).toContain('/info');
});

it('does not replay an upload if the management scope changes', async () => {
  uploadStatus = 19704;
  await expect(uploadFileToServerApi('4322', new File(['notes'], 'notes.txt'))).rejects.toMatchObject({ status_code: 19704 });
  expect(mockCalls.filter(call => call.url?.includes('/upload/'))).toHaveLength(1);
});

it('retains compatibility with backends that do not send a management tenant header', async () => {
  scopeHeader = undefined;
  await expect(uploadFileToServerApi('4322', new File(['notes'], 'notes.txt'))).resolves.toMatchObject({ file_path: '/tmp/notes.txt' });
});

it('preserves caller headers on multipart requests', async () => {
  await request.postMultiPart('/api/v1/knowledge/upload/4322', new FormData(), { headers: { 'X-Management-Tenant': '3' } });
  expect(mockCalls[0].tenant).toBe('3');
});
