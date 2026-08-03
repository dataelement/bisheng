import { readFileSync } from 'node:fs';

import {
  notifyPortalAuthRequired,
  PORTAL_AUTH_REQUIRED_MESSAGE,
  type PortalAuthWindow,
} from './portalAuthBridge';

function createWindow(search: string, embedded = true) {
  const postMessage = jest.fn();
  const parent = { postMessage };
  const currentWindow = {
    location: { search },
    parent: embedded ? parent : undefined,
  } as unknown as PortalAuthWindow;
  if (!embedded) currentWindow.parent = currentWindow;
  return { currentWindow, postMessage };
}

test('embedded portal page notifies its parent when authentication is required', () => {
  const { currentWindow, postMessage } = createWindow('?portal_embed=1');

  expect(notifyPortalAuthRequired(currentWindow)).toBe(true);
  expect(postMessage).toHaveBeenCalledWith({ type: PORTAL_AUTH_REQUIRED_MESSAGE }, '*');
});

test.each([
  ['standalone page', '?portal_embed=1', false],
  ['non-portal iframe', '?from=other', true],
])('%s keeps the existing 401 handling path', (_name, search, embedded) => {
  const { currentWindow, postMessage } = createWindow(search, embedded);

  expect(notifyPortalAuthRequired(currentWindow)).toBe(false);
  expect(postMessage).not.toHaveBeenCalled();
});

test('the HTTP interceptor delegates embedded 401 handling to the portal bridge', () => {
  const requestSource = readFileSync('src/api/request.ts', 'utf8');
  expect(requestSource).toMatch(/notifyPortalAuthRequired\(\)/);
});
