import {
  LOGIN_PATHNAME_AT_KEY,
  LOGIN_PATHNAME_KEY,
  __resetRedirectGuardForTests,
  buildReturnTo,
  getLoginUrl,
  redirectToLogin,
} from './loginRedirect';

const ORIGIN = 'http://localhost:3080';

/**
 * jsdom refuses real navigation (`Not implemented: navigation`), so swap in a
 * plain object we can read `href` back from.
 */
function stubLocation(partial: { pathname?: string; search?: string; hash?: string }) {
  const stub = {
    origin: ORIGIN,
    pathname: partial.pathname ?? '/',
    search: partial.search ?? '',
    hash: partial.hash ?? '',
    href: `${ORIGIN}${partial.pathname ?? '/'}`,
  };
  Object.defineProperty(window, 'location', {
    value: stub,
    writable: true,
    configurable: true,
  });
  return stub;
}

beforeEach(() => {
  localStorage.clear();
  __resetRedirectGuardForTests();
});

describe('buildReturnTo', () => {
  it('keeps the query string and hash, not just the pathname', () => {
    stubLocation({ pathname: '/workspace/share/tok', search: '?from=im', hash: '#result' });
    expect(buildReturnTo()).toBe('/workspace/share/tok?from=im#result');
  });
});

describe('getLoginUrl', () => {
  it('prefers the configured SSO url', () => {
    stubLocation({ pathname: '/workspace/share/tok' });
    localStorage.setItem('THIRD_PARTY_LOGIN_URL', 'https://idp.example.com/authorize');
    expect(getLoginUrl()).toBe('https://idp.example.com/authorize');
  });

  it('falls back to the platform login when no SSO url is stored', () => {
    stubLocation({ pathname: '/workspace/share/tok' });
    expect(getLoginUrl()).toBe(`${ORIGIN}/admin`);
  });
});

describe('redirectToLogin', () => {
  it('stores the return target as an absolute same-origin url and navigates to login', () => {
    const loc = stubLocation({ pathname: '/workspace/share/tok', search: '?v=2' });

    redirectToLogin();

    expect(localStorage.getItem(LOGIN_PATHNAME_KEY)).toBe(
      `${ORIGIN}/workspace/share/tok?v=2`,
    );
    expect(Number(localStorage.getItem(LOGIN_PATHNAME_AT_KEY))).toBeGreaterThan(0);
    expect(loc.href).toBe(`${ORIGIN}/admin`);
  });

  it('drops the auth-state sentinel so the next login counts as a fresh session', () => {
    stubLocation({ pathname: '/workspace/share/tok' });
    localStorage.setItem('bs:auth-state', '42');

    redirectToLogin();

    expect(localStorage.getItem('bs:auth-state')).toBeNull();
  });

  it('navigates once even when several 401s land together', () => {
    const loc = stubLocation({ pathname: '/workspace/share/tok' });

    redirectToLogin();
    loc.href = 'sentinel';
    redirectToLogin('/workspace/c/new');

    expect(loc.href).toBe('sentinel');
    expect(localStorage.getItem(LOGIN_PATHNAME_KEY)).toBe(`${ORIGIN}/workspace/share/tok`);
  });

  it('still navigates for a forced (user-initiated) retry', () => {
    const loc = stubLocation({ pathname: '/workspace/share/tok' });

    redirectToLogin();
    loc.href = 'sentinel';
    redirectToLogin('/workspace/share/tok', { force: true });

    expect(loc.href).toBe(`${ORIGIN}/admin`);
  });

  it('refuses to persist a foreign origin as the return target', () => {
    stubLocation({ pathname: '/workspace/share/tok' });

    redirectToLogin('https://evil.example.com/steal');

    expect(localStorage.getItem(LOGIN_PATHNAME_KEY)).toBeNull();
  });
});
