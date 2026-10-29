import { normalizeApiError } from '@bisheng/api-client';
import request from './request';
import { getCitationDetail } from './chatApi';
jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn() } }));
it.each(['expired', 'forbidden'])('preserves failure evidence through the citation %s recovery', async reason => {
  const response = { status: 404, data: { status_code: 404, data: { reason } } };
  const error = normalizeApiError(Object.assign(new Error('HTTP404'), { response }), { message: 'Citation unavailable' });
  error.presentation = 'toast';
  (request.get as jest.Mock).mockRejectedValue(error);
  const rejected = await getCitationDetail(`test-${reason}`).catch(cause => cause);
  expect(rejected).toBe(error);
  expect(rejected).toMatchObject({ httpStatus: 404, status_code: 404, data: { reason }, citationExpired: reason === 'expired', citationForbidden: reason === 'forbidden', presentation: 'toast' });
  expect(rejected.response).toBe(response);
});
