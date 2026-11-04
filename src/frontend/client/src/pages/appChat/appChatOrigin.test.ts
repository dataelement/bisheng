import {
  copyAppChatReturnTo,
  deriveAppChatOriginFromEntry,
  normalizeAppChatReturn,
  resolveAppChatExitNavigateTarget,
  writeAppChatReturnTo,
} from './appChatOrigin';

beforeEach(() => sessionStorage.clear());

it.each(['/square?type=apps', '/workspace/square?type=apps'])('accepts the apps square at %s', path => {
  expect(normalizeAppChatReturn(path)).toBe('/square?type=apps');
  expect(deriveAppChatOriginFromEntry(`?returnTo=${encodeURIComponent(path)}`, null)).toBe('explore');
  expect(deriveAppChatOriginFromEntry('', { appSurfaceReturn: path })).toBe('explore');
});

it.each(['/square?type=skills', '/square?type=apps&next=https://example.com', 'https://example.com/square?type=apps', '//example.com/square?type=apps'])('keeps unsupported return targets outside the allowlist: %s', path => {
  expect(normalizeAppChatReturn(path)).toBeNull();
});

it('preserves square return through new conversations and query removal', () => {
  writeAppChatReturnTo('original', '/square?type=apps');
  copyAppChatReturnTo('original', 'next');
  expect(resolveAppChatExitNavigateTarget('next', { search: '' })).toBe('/square?type=apps');
});

it.each(['/apps', '/apps/explore', '/c/new'] as const)('preserves the existing %s return contract', path => {
  expect(resolveAppChatExitNavigateTarget(undefined, { search: `?returnTo=${encodeURIComponent(path)}` })).toBe(path);
  expect(resolveAppChatExitNavigateTarget(undefined, { search: '', state: { appSurfaceReturn: path } })).toBe(path);
});
