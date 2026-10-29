import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import i18next from 'i18next';
import messages from '../../public/locales/en-US/api_errors.json';
import request, { showApiError } from './request';
import { ApiError } from '@bisheng/api-client';
const notices = vi.hoisted(() => vi.fn());
vi.mock('@bisheng/ui', () => ({ notification: { open: notices } }));
const adapter = request.defaults.adapter;
beforeAll(async () => { await i18next.init({ lng: 'en', resources: { en: { api_errors: messages, translation: { prompt: 'Notice' } } } }); });
afterEach(() => { notices.mockClear(); request.defaults.adapter = adapter; vi.restoreAllMocks(); });
it.each([new Error('SQL secret'), 'stack at /private', { message: 'secret' }, [{ msg: 'secret' }], { status_code: 49999, status_message: 'secret' }])('never displays arbitrary evidence: %p', cause => {
 const error = showApiError(cause);
 expect(error.message).toBe(messages.fallback);
 expect(error.cause).toBe(cause);
 expect(notices).toHaveBeenCalledWith(expect.objectContaining({ description: messages.fallback }));
});
it('handles cyclic evidence without serialization and retains canonical identity', () => {
 const cause: { self?: unknown } = {}; cause.self = cause;
 const error = new ApiError(cause, { message: 'private stack' });
 expect(showApiError(error)).toBe(error);
 expect(error.cause).toBe(cause);
 expect(error.message).toBe(messages.fallback);
 showApiError(error); expect(notices).toHaveBeenCalledTimes(1);
});
it('retains specific translated business context but excludes technical parameters', async () => {
 for (const [code, data] of [[10019, { exception: 'SECRET /stack' }], [19403, { used_gb: 2, quota_gb: 3 }]] as const) {
 request.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: { status_code: code, status_message: 'secret', data } });
 const error = await request.get('/test').catch(cause => cause);
 expect(error.message).not.toContain('SECRET');
 expect(error.message).not.toBe(messages.fallback);
 expect(error.data).toEqual(data);
 if (code === 19403) expect(error.message).toContain('2/3');
 }
});
it.each([['ERR_NETWORK', 'network_error'], ['ECONNABORTED', 'request_timeout']] as const)('localizes %s and keeps canceled failures quiet', (code, key) => {
 expect(showApiError({ code }).message).toBe((messages as Record<string, string>)[key]);
 notices.mockClear(); showApiError({ code: 'ERR_CANCELED' }); expect(notices).not.toHaveBeenCalled();
});
it('does not treat backend parameters as translation settings or inherit message aliases', () => {
 const error = showApiError({ status_code: 26130, data: { defaultValue: 'PRIVATE', lng: 'missing', ns: 'missing' } });
 expect(error.message).toBe(messages['26130']);
 expect(showApiError({ status_code: 49999, status_message: 'constructor' }).message).toBe(messages.fallback);
});
it('sanitizes an already canonical rejection even when automatic display is disabled', async () => {
 const error = new ApiError(new Error('PRIVATE'), { message: 'PRIVATE' });
 request.defaults.adapter = async config => { throw Object.assign(error, { config }); };
 expect(await request.get('/test', { showError: false }).catch(cause => cause)).toBe(error);
 expect(error.message).toBe(messages.fallback); expect(notices).not.toHaveBeenCalled();
});

it('keeps a readable fallback before translations have initialized', () => {
 vi.spyOn(i18next, 'exists').mockReturnValue(false);
 vi.spyOn(i18next, 't').mockReturnValue(undefined as never);
 expect(showApiError(new Error('PRIVATE')).message).toBe('Request failed. Please try again.');
});
