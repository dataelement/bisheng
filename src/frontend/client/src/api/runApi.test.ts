/**
 * F004: the run calls go through the real response interceptors. A business
 * error envelope (HTTP 200) rejects with the translated message, shows no
 * toast from the request layer, and never redirects the page on a 403.
 */
import request, { prepareBrowserHeaders } from './request';
import { getRunQueuePosition, sendRunMessage, stopConversationRun } from './runApi';

jest.mock('axios', () => {
  const actual = jest.requireActual('axios');
  const instance = actual.create();
  return { __esModule: true, ...actual, default: { ...actual, create: () => instance } };
});
jest.mock('~/api/chat/headers-helpers', () => ({ setTokenHeader: jest.fn() }));
jest.mock('~/utils/loginRedirect', () => ({ redirectToLogin: jest.fn() }));
const MESSAGES: Record<string, string> = {
  'api_errors.12045': 'The department is full.',
  'api_errors.403': 'You have no access.',
};
jest.mock('i18next', () => ({
  __esModule: true,
  default: {
    exists: (key: string) => key in MESSAGES,
    t: (key: string, options?: { defaultValue?: string }) => MESSAGES[key] ?? options?.defaultValue ?? key,
  },
}));

const transport = (jest.requireMock('axios') as typeof import('axios')).default.create();
const adapter = transport.defaults.adapter;
const toast = jest.fn();

function answerWith(envelope: Record<string, unknown>) {
  transport.defaults.adapter = async (config) => ({ config, status: 200, statusText: 'OK', headers: {}, data: envelope });
}

beforeEach(async () => {
  // Establish the browser management scope the request layer checks, as the
  // request contract tests do.
  answerWith({ status_code: 200, data: { scope_tenant_id: 60, source: 'own' } });
  await request.post('/api/v1/user/login', {});
  await prepareBrowserHeaders('GET', '/api/v1/test-run');
  window.showToast = toast;
  localStorage.removeItem('ERROR_REQUEST_PATH');
});
afterEach(() => {
  transport.defaults.adapter = adapter;
  toast.mockClear();
});

const calls: Array<[string, () => Promise<unknown>]> = [
  ['send', () => sendRunMessage({ text: 'hi' })],
  ['stop', () => stopConversationRun('c1', 'r1')],
  ['queue position', () => getRunQueuePosition('c1')],
];

describe.each(calls)('%s', (_name, call) => {
  it('rejects a business error envelope with the translated message and no toast', async () => {
    answerWith({ status_code: 12045, status_message: 'department full', data: { exception: 'x' } });
    const error = await call().catch((cause) => cause);
    expect(error).toBeInstanceOf(Error);
    expect(error).toMatchObject({ status_code: 12045, kind: 'business', message: 'The department is full.' });
    expect(toast).not.toHaveBeenCalled();
  });

  it('rejects a business 403 without redirecting the page', async () => {
    const before = window.location.href;
    answerWith({ status_code: 403, status_message: 'forbidden', data: null });
    const error = await call().catch((cause) => cause);
    expect(error).toMatchObject({ status_code: 403, message: 'You have no access.' });
    expect(window.location.href).toBe(before);
    expect(localStorage.getItem('ERROR_REQUEST_PATH')).toBeNull();
    expect(toast).not.toHaveBeenCalled();
  });
});

it('resolves a successful send with the envelope', async () => {
  const envelope = { status_code: 200, data: { run_id: 'r1', disposition: 'started', message_id: '1' } };
  answerWith(envelope);
  await expect(sendRunMessage({ text: 'hi' })).resolves.toEqual(envelope);
});
