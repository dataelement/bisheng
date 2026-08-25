import { readFileSync } from 'node:fs';
import {
  notifyPortalRateLimit,
  PORTAL_RATE_LIMIT_MESSAGE,
  type PortalRateLimitWindow,
} from './portalRateLimitBridge';

function createWindow(search: string, embedded = true) {
  const postMessage = jest.fn();
  const parent = { postMessage };
  const currentWindow = {
    location: { search },
    parent: embedded ? parent : undefined,
  } as unknown as PortalRateLimitWindow;
  if (!embedded) currentWindow.parent = currentWindow;
  return { currentWindow, postMessage };
}

test('embedded portal rate limits are forwarded with a bounded public payload', () => {
  const { currentWindow, postMessage } = createWindow('?portal_embed=1');

  expect(notifyPortalRateLimit({ code: 10042, message: '  系统繁忙，请稍后重试  ' }, currentWindow)).toBe(true);
  expect(postMessage).toHaveBeenCalledWith({
    type: PORTAL_RATE_LIMIT_MESSAGE,
    code: 10042,
    message: '系统繁忙，请稍后重试',
  }, '*');
});

test.each([
  ['standalone page', '?portal_embed=1', false],
  ['non-portal iframe', '?from=other', true],
])('%s keeps rate-limit handling inside Client', (_name, search, embedded) => {
  const { currentWindow, postMessage } = createWindow(search, embedded);

  expect(notifyPortalRateLimit({ code: 10042, message: 'busy' }, currentWindow)).toBe(false);
  expect(postMessage).not.toHaveBeenCalled();
});

test('the HTTP interceptor forwards embedded rate limits to the portal bridge', () => {
  const requestSource = readFileSync('src/api/request.ts', 'utf8');

  expect(requestSource).toMatch(/notifyPortalRateLimit\(/);
  expect(requestSource).toMatch(/error\.response\.status === 429[\s\S]*handleRateLimitResponse/);
  expect(requestSource).toMatch(/response\.data\?\.status_code === API_RATE_LIMIT_CODE/);
});
