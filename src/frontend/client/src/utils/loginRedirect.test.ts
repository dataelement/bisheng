import {
  LOGIN_PATHNAME_AT_KEY,
  LOGIN_PATHNAME_KEY,
  __resetRedirectGuardForTests,
  buildReturnTo,
  getLoginUrl,
  redirectToLogin,
} from './loginRedirect';
import { resolvePlatformOrigin } from './platformAdminUrl';

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

  it('uses the platform origin injected for local dev instead of this origin', () => {
    // `vite` serve injects PLATFORM_ORIGIN (:3001) so a logged-out visit lands on
    // the platform login page rather than this app's own 404 — see vite.config.ts.
    const appEnv = globalThis as unknown as {
      __APP_ENV__: { BASE_URL: string; PLATFORM_ORIGIN?: string };
    };
    const previous = appEnv.__APP_ENV__;
    appEnv.__APP_ENV__ = { ...previous, PLATFORM_ORIGIN: 'http://localhost:3001/' };
    try {
      stubLocation({ pathname: '/workspace/share/tok' });
      expect(getLoginUrl()).toBe('http://localhost:3001/admin');
    } finally {
      appEnv.__APP_ENV__ = previous;
    }
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

describe('resolvePlatformOrigin', () => {
  it('derives the platform dev port from the browser host (127.0.0.1 / LAN IP)', () => {
    expect(resolvePlatformOrigin({}, { protocol: 'http:', hostname: '127.0.0.1' }, true)).toBe(
      'http://127.0.0.1:3001',
    );
    expect(resolvePlatformOrigin({}, { protocol: 'http:', hostname: '192.168.1.88' }, true)).toBe(
      'http://192.168.1.88:3001',
    );
  });

  it('prefers an explicitly configured origin', () => {
    expect(
      resolvePlatformOrigin({ PLATFORM_ORIGIN: 'https://admin.example.com/' }, { hostname: 'x' }, true),
    ).toBe('https://admin.example.com');
  });

  it('falls back to the current origin outside dev', () => {
    expect(
      resolvePlatformOrigin(
        {},
        { origin: 'http://192.168.1.88:4001', hostname: '192.168.1.88' },
        false,
      ),
    ).toBe('http://192.168.1.88:4001');
  });
});
