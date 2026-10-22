import { ApiError } from '@bisheng/api-client';
import request, { showApiError, translateApiErrorMessage } from './request';

jest.mock('axios', () => {
  const actual = jest.requireActual('axios');
  const instance = actual.create();
  return { __esModule: true, ...actual, default: { ...actual, create: () => instance } };
});
jest.mock('~/api/chat/headers-helpers', () => ({ setTokenHeader: jest.fn() }));
jest.mock('~/utils/loginRedirect', () => ({ redirectToLogin: jest.fn() }));
jest.mock('i18next', () => ({ __esModule: true, default: { exists: () => false, t: (key: string) => key } }));
const transport = (jest.requireMock('axios') as typeof import('axios')).default.create();
const adapter = transport.defaults.adapter;
const toast = jest.fn();
beforeEach(() => { window.showToast = toast; });
afterEach(() => { transport.defaults.adapter = adapter; toast.mockClear(); });

it.each([{}, { skip403Redirect: true, showError: false }])('rejects business failures without displaying silent requests: %p', async options => {
  transport.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 11055, status_message: 'duplicate', data: { skill_id: 4 } } });
  const error = await request.get('/test', options).catch(cause => cause);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status_code: 11055, httpStatus: 200, data: { skill_id: 4 } });
  expect(toast).not.toHaveBeenCalled();
});

it('shows an opted-in error once while preserving the rejected error', async () => {
  transport.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: 26130, status_message: 'conflict' } });
  const error = await request.get('/test', { showError: true }).catch(cause => cause);
  expect(error).toBeInstanceOf(ApiError);
  showApiError(error);
  expect(toast).toHaveBeenCalledTimes(1);
});

it('preserves decoded binary errors and original transport evidence', async () => {
  const blob = new Blob(['{"status_code":12064,"status_message":"export failed","data":{"file":"a"}}'], { type: 'application/json' });
  transport.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: blob });
  const error = await request.postResponse('/test', {}, { responseType: 'blob' }).catch(cause => cause);
  expect(error).toMatchObject({ status_code: 12064, data: { file: 'a' } });
  expect(error).toBeInstanceOf(ApiError);
  if (!(error instanceof ApiError)) throw new Error('Expected a structured error');
  expect(error.response?.data).toBe(blob);
});

it('does not wrap successful response bodies or change full-response downloads', async () => {
  transport.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: { 'content-disposition': 'test' }, data: { status_code: 200, data: { id: 4 } } });
  expect(await request.get('/test')).toEqual({ status_code: 200, data: { id: 4 } });
  const response = await request.getResponse<{ headers: unknown; data: unknown }>('/test');
  expect(response.headers).toHaveProperty('content-disposition', 'test');
});

it('decodes validation arrays and unresolved templates into readable text', () => {
  expect(translateApiErrorMessage({ status_code: 49999, status_message: [{ msg: 'required' }, { message: 'invalid' }] })).toBe('required; invalid');
  expect(translateApiErrorMessage({ status_code: 49999, status_message: '{message}', data: { message: 'clear reason' } })).toBe('clear reason');
});

it('runs maintenance handling for a binary business error before marking it handled', async () => {
  const listener = jest.fn();
  window.addEventListener('bs:service-maintenance', listener);
  const blob = new Blob(['{"status_code":500,"status_message":"maintenance"}'], { type: 'application/json' });
  transport.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: blob });
  try {
    const error = await request.get('/test', { responseType: 'blob' }).catch(cause => cause);
    expect(error).toMatchObject({ status_code: 500, presentation: 'global' });
    expect(listener).toHaveBeenCalledTimes(1);
    expect(toast).not.toHaveBeenCalled();
  } finally { window.removeEventListener('bs:service-maintenance', listener); }
});

it.each([403, 11001])('preserves global handling for binary business error %s', async code => {
  const previous = window.location;
  const location = { href: previous.href, pathname: previous.pathname };
  Object.defineProperty(window, 'location', { configurable: true, value: location });
  const blob = new Blob([JSON.stringify({ status_code: code, status_message: 'global failure' })], { type: 'application/json' });
  transport.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: blob });
  try {
    const error = await request.get('/test', { responseType: 'blob' }).catch(cause => cause);
    expect(error).toMatchObject({ status_code: code, presentation: 'global' });
    if (code === 403) expect(location.href).toContain('/c/new?error=11403');
    else expect(toast).toHaveBeenCalledTimes(1);
    showApiError(error);
    expect(toast).toHaveBeenCalledTimes(code === 403 ? 0 : 1);
  } finally { Object.defineProperty(window, 'location', { configurable: true, value: previous }); }
});

it('retains an HTTP failure body even when the binary MIME is absent', async () => {
  const blob = new Blob(['{"status_code":26130,"data":{"version":8}}']);
  const response = { status: 409, data: blob };
  transport.defaults.adapter = async config => { throw Object.assign(new Error('HTTP 409'), { config, response }); };
  const error = await request.get('/test', { responseType: 'blob' }).catch(cause => cause);
  expect(error).toMatchObject({ httpStatus: 409, status_code: 26130, data: { version: 8 }, presentation: 'none' });
  if (!(error instanceof ApiError)) throw new Error('Expected a structured error');
  expect(error.response?.data).toBe(blob);
});
