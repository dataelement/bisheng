import { getShareTokenFromPath } from './shareToken';

describe('getShareTokenFromPath', () => {
    const origEnv = (global as any).__APP_ENV__;

    beforeEach(() => {
        (global as any).__APP_ENV__ = { ...origEnv, BASE_URL: '/workspace' };
    });

    afterEach(() => {
        (global as any).__APP_ENV__ = origEnv;
    });

    it('reads the token off a bare share route', () => {
        expect(getShareTokenFromPath('/workspace/share/iNma0ErLIIST8eRC4IpGve6NNmfASCTp')).toBe(
            'iNma0ErLIIST8eRC4IpGve6NNmfASCTp',
        );
    });

    it('ignores the optional trailing version id', () => {
        expect(getShareTokenFromPath('/workspace/share/abc/0f71102e2fef4657883c514eeb886b7f')).toBe('abc');
    });

    // The token is the only grant a share recipient has; a route that is not a
    // share page must never send one (it would widen an ordinary request).
    it('returns empty outside the share route', () => {
        expect(getShareTokenFromPath('/workspace/c/new')).toBe('');
        expect(getShareTokenFromPath('/workspace/html')).toBe('');
        expect(getShareTokenFromPath('/workspace/knowledge/share/42')).toBe('');
        expect(getShareTokenFromPath('/workspace/share')).toBe('');
        expect(getShareTokenFromPath('/workspace/share/')).toBe('');
    });

    it('decodes a percent-encoded token', () => {
        expect(getShareTokenFromPath('/workspace/share/a%2Bb')).toBe('a+b');
    });

    // decodeURIComponent throws on a lone '%'; an opaque token is still usable.
    it('falls back to the raw segment when the token is not valid encoding', () => {
        expect(getShareTokenFromPath('/workspace/share/100%')).toBe('100%');
    });

    it('works when the app is served from the domain root', () => {
        (global as any).__APP_ENV__ = { ...origEnv, BASE_URL: '/' };
        expect(getShareTokenFromPath('/share/abc')).toBe('abc');
    });
});
