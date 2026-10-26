import { ApiError } from '@bisheng/api-client';
import request, { showApiError, translateApiErrorMessage } from './request';

jest.mock('axios', () => {
  const actual = jest.requireActual('axios');
  const instance = actual.create();
  return { __esModule: true, ...actual, default: { ...actual, create: () => instance } };
});
jest.mock('~/api/chat/headers-helpers', () => ({ setTokenHeader: jest.fn() }));
jest.mock('~/utils/loginRedirect', () => ({ redirectToLogin: jest.fn() }));
import i18next from 'i18next';
import messages from '../../../packages/locales/src/api_errors/en.json';
beforeAll(async () => { await i18next.init({ lng: 'en', resources: { en: { translation: { api_errors: messages } } } }); });
const transport = (jest.requireMock('axios') as typeof import('axios')).default.create();
const adapter = transport.defaults.adapter;
const toast = jest.fn();
beforeEach(() => { window.showToast = toast; });
afterEach(() => { transport.defaults.adapter = adapter; toast.mockClear(); });


it.each([new Error('SQL secret'), 'stack at /private', { message: 'secret' }, [{ msg: 'secret' }]])('does not expose arbitrary failure evidence: %p', cause => {
 const error = showApiError(cause);
 expect(error.message).toBe(messages.fallback); expect(error.cause).toBe(cause);
 expect(toast).toHaveBeenCalledWith(expect.objectContaining({ message: messages.fallback }));
});
it('keeps canonical identity and evidence while replacing unsafe display copy', () => {
 const cause: { self?: unknown } = {}; cause.self = cause;
 const error = new ApiError(cause, { message: 'private stack' });
 expect(showApiError(error)).toBe(error); expect(error.cause).toBe(cause);
 expect(error.message).toBe(messages.fallback); showApiError(error); expect(toast).toHaveBeenCalledTimes(1);
});
it('uses the registered catalog, never unknown server messages or technical interpolation', () => {
 expect(translateApiErrorMessage({ status_code: 49999, status_message: [{ msg: 'private' }] })).toBe(messages.fallback);
 expect(translateApiErrorMessage({ status_code: 10019, data: { exception: 'SECRET' } })).not.toContain('SECRET');
 expect(translateApiErrorMessage({ status_code: 19403, data: { used_gb: 2, quota_gb: 3 } })).toContain('2/3');
});
it('normalizes silent transport failures without exposing their message', async () => {
 transport.defaults.adapter = async config => { throw Object.assign(new Error('private URL'), { config, code: 'ERR_NETWORK' }); };
 const error = await request.get('/test').catch(cause => cause);
 if (!(error instanceof ApiError)) throw new Error('Expected ApiError');
 expect(error.message).toBe((messages as Record<string,string>).network_error);
 expect(toast).not.toHaveBeenCalled();
 showApiError(error); expect(toast).toHaveBeenCalledTimes(1);
});
it('does not treat backend parameters as translation settings', () => {
 expect(translateApiErrorMessage({ status_code: 26130, data: { defaultValue: 'PRIVATE', lng: 'missing', ns: 'missing' } })).toBe(messages['26130']);
});
it('sanitizes an already canonical rejection without changing identity or silent behavior', async () => {
 const error = new ApiError(new Error('PRIVATE'), { message: 'PRIVATE' });
 transport.defaults.adapter = async config => { throw Object.assign(error, { config }); };
 expect(await request.get('/test').catch(cause => cause)).toBe(error);
 expect(error.message).toBe(messages.fallback); expect(toast).not.toHaveBeenCalled();
});

it('keeps a readable fallback before translations have initialized', () => {
 jest.spyOn(i18next, 'exists').mockReturnValue(false);
 jest.spyOn(i18next, 't').mockReturnValue(undefined as never);
 expect(showApiError(new Error('PRIVATE')).message).toBe('Request failed. Please try again.');
});
