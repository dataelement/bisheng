import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import i18next from 'i18next';
import messages from '../../public/locales/en-US/api_errors.json';
import request, { showApiError } from './request';

const notices = vi.hoisted(() => vi.fn());
vi.mock('@bisheng/ui', () => ({ notification: { open: notices } }));
const adapter = request.defaults.adapter;
beforeEach(async () => {
  notices.mockClear();
  await i18next.init({ lng: 'en', resources: { en: { api_errors: messages } }, initImmediate: false });
});
afterEach(() => { request.defaults.adapter = adapter; });

it.each([
  ['ERR_NETWORK', 'Unable to connect to the server. Check your network connection and try again.'],
  ['ECONNABORTED', 'The request timed out. Check whether the operation completed before trying again.'],
  ['ETIMEDOUT', 'The request timed out. Check whether the operation completed before trying again.'],
])('presents readable %s feedback once and retains its diagnostic cause', async (code, message) => {
  const cause = Object.assign(new Error('Technical transport details'), { code });
  request.defaults.adapter = async config => { throw Object.assign(cause, { config }); };
  const error = await request.get('/test').catch(reason => reason);
  expect(error.message).toBe(message);
  expect(error.cause).toBe(cause);
  expect(cause.message).toBe('Technical transport details');
  showApiError(error);
  expect(notices).toHaveBeenCalledTimes(1);
  expect(notices).toHaveBeenCalledWith(expect.objectContaining({ description: message }));
});
