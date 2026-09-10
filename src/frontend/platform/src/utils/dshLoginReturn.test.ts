import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { consumeLoginReturnTo, hasDesktopLoginReturnTo, rememberDesktopLoginReturnTo } from './loginReturnTo'
beforeEach(() => {
    const values = new Map<string, string>()
    vi.stubGlobal('localStorage', {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
    })
})
afterEach(() => vi.unstubAllGlobals())
describe('desktop SSO handoff', () => {
    it('allows a fresh same-origin desktop return without consuming it early', () => {
        localStorage.setItem('LOGIN_PATHNAME', '/desktop-login?auth_id=fixture')
        localStorage.setItem('LOGIN_PATHNAME_AT', String(Date.now()))
        expect(hasDesktopLoginReturnTo()).toBe(true)
        expect(consumeLoginReturnTo()).toBe(
            `${location.origin}/desktop-login?auth_id=fixture`,
        )
        expect(hasDesktopLoginReturnTo()).toBe(false)
    })
    it('rejects stale, external and non-desktop targets', () => {
        for (const target of [
            'https://evil.example/desktop-login',
            '/sys',
            '//evil.example/desktop-login',
        ]) {
            localStorage.setItem('LOGIN_PATHNAME', target)
            localStorage.setItem('LOGIN_PATHNAME_AT', String(Date.now()))
            expect(hasDesktopLoginReturnTo()).toBe(false)
        }
        localStorage.setItem('LOGIN_PATHNAME', '/desktop-login')
        localStorage.setItem('LOGIN_PATHNAME_AT', String(Date.now() - 700000))
        expect(hasDesktopLoginReturnTo()).toBe(false)
    })
})


it('does not overwrite workspace return targets on ordinary login pages', () => {
    localStorage.setItem('LOGIN_PATHNAME', '/workspace/chat/session')
    localStorage.setItem('LOGIN_PATHNAME_AT', String(Date.now()))
    vi.stubGlobal('location', { origin: 'http://bisheng.example', pathname: '/', href: 'http://bisheng.example/' })
    rememberDesktopLoginReturnTo()
    expect(consumeLoginReturnTo()).toBe('http://bisheng.example/workspace/chat/session')
})
