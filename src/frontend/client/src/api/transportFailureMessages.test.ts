import i18next from 'i18next';
import { ApiError } from '@bisheng/api-client';
import messages from '../locales/en/api_errors.gen.json';
import request, { showApiError } from './request';

jest.mock('axios', () => {
  const actual = jest.requireActual('axios');
  const instance = actual.create();
  return { __esModule: true, ...actual, default: { ...actual, create: () => instance } };
});
const transport = (jest.requireMock('axios') as typeof import('axios')).default.create();
const adapter = transport.defaults.adapter;
const notify = jest.fn();
beforeEach(async () => {
  window.showToast = notify;
  await i18next.init({ lng: 'en', resources: { en: { translation: { api_errors: messages } } }, initImmediate: false });
});
afterEach(() => { transport.defaults.adapter = adapter; });

it.each([
  ['ERR_NETWORK', 'Unable to connect to the server. Check your network connection and try again.'],
  ['ECONNABORTED', 'The request timed out. Check whether the operation completed before trying again.'],
  ['ETIMEDOUT', 'The request timed out. Check whether the operation completed before trying again.'],
])('presents readable %s feedback once and retains its diagnostic cause', async (code, message) => {
  const cause = Object.assign(new Error('Technical transport details'), { code });
  transport.defaults.adapter = async config => { throw Object.assign(cause, { config }); };
  const error = await request.get('/test').catch(reason => reason);
  expect(error).toBeInstanceOf(ApiError);
  if (!(error instanceof ApiError)) throw new Error('Expected a structured request error');
  expect(error.message).toBe(message);
  expect(error.cause).toBe(cause);
  expect(cause.message).toBe('Technical transport details');
  showApiError(error);
  showApiError(error);
  expect(notify).toHaveBeenCalledTimes(1);
  expect(notify).toHaveBeenCalledWith(expect.objectContaining({ message }));
});
