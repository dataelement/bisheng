import { resolveKnowledgeParseFailureMessage } from './knowledgeParseFailureMessage';
import { localizedBusinessFailure } from '~/utils/failureInfo';
import { resolveLocalizedKnowledgeImportError } from '~/pages/knowledge/webLinkI18n';
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
import { knowledgeProcessing } from '../locales/en/translation.json';
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


it.each([
 ['source_file_move_input_required', knowledgeProcessing.conflict.source_file_input],
 ['source_space_move_input_required', knowledgeProcessing.conflict.source_input],
])('shows the localized source dependency for %s', (reason, expected) => {
 i18next.addResourceBundle('en', 'translation', { knowledgeProcessing });
 expect(translateApiErrorMessage({ status_code: 10999, data: { reason } })).toBe(expected);
});

it('explains the observed knowledge operation and keeps unknown diagnostics private', () => {
 i18next.addResource('en', 'translation', 'knowledgeProcessing.conflict.file_queue', 'This file is queued. View Task history.');
 const error = {status_code: 10999, data: {reason: 'processing_file_state_not_ready', blocking_operation: 'file_waiting', exception: 'PRIVATE'}};
 expect(translateApiErrorMessage(error)).toBe('This file is queued. View Task history.');
 expect(translateApiErrorMessage({status_code: 10999, data: {reason: 'PRIVATE', blocking_operation: '__proto__'}})).toBe(messages['10999']);
});


it('shows the failing node and missing model through the HTTP error presenter', async () => {
 const envelope = { status_code: 10996, status_message: 'PRIVATE', data: { reason: 'reference_target_invalid', reference_errors: [{
  node_id: 'llm_b1ef4', node_name: 'LLM', resource_type: 'model', target_id: '375', state: 'invalid_missing',
 }] } };
 transport.defaults.adapter = async config => ({ config, status: 200, statusText: 'OK', headers: {}, data: envelope });
 const error = await request.get('/test').catch(cause => cause);
 if (!(error instanceof ApiError)) throw new Error('Expected ApiError');
 expect(error).toMatchObject({ status_code: 10996, data: envelope.data });
 expect(error.message).toContain('LLM'); expect(error.message).toContain('375');
 expect(error.message).toContain('does not exist'); expect(error.message).not.toContain('PRIVATE');
 showApiError(error);
 expect(toast).toHaveBeenCalledWith(expect.objectContaining({ message: error.message }));
});


it('keeps exact causes in parse failures, task failures and knowledge import errors', () => {
 const data = { reason: 'reference_target_invalid', exception: 'PRIVATE', reference_errors: [{ resource_type: 'knowledge_file', target_id: '17', state: 'invalid_deleted' }] };
 const localize = (key: string, values?: Record<string, unknown>) => String(i18next.t(key as Parameters<typeof i18next.t>[0], values ?? {}));
 const results = [
  resolveKnowledgeParseFailureMessage({ code: 10996, data }),
  localizedBusinessFailure(10996, localize, data),
  resolveLocalizedKnowledgeImportError({ status_code: 10996, data }, localize, 'api_errors.fallback'),
 ];
 for (const message of results) {
  expect(message).toContain('knowledge file (ID: 17) has been deleted');
  expect(message).not.toContain('PRIVATE');
 }
});
