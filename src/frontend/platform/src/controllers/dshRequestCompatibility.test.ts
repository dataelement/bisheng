import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const captured = vi.hoisted(() => ({
    failed: null as null | ((value: unknown) => Promise<unknown>),
    success: null as null | ((value: unknown) => Promise<unknown>),
    toast: vi.fn(),
}))
vi.mock('axios', () => ({
    default: {
        defaults: {},
        create: () => ({
            interceptors: {
                request: { use: vi.fn() },
                response: {
                    use: (
                        success: (value: unknown) => Promise<unknown>,
                        failed: (value: unknown) => Promise<unknown>,
                    ) => {
                        captured.failed = failed
                        captured.success = success
                    },
                },
            },
        }),
    },
}))
vi.mock('@/components/bs-ui/toast/use-toast', () => ({ toast: captured.toast }))
vi.mock('i18next', () => ({ default: { t: (key: string) => key } }))
import './request'
import { consumeLoginReturnTo, rememberDesktopLoginReturnTo } from '@/utils/loginReturnTo'
import { isDshRequestRejected } from './API/dsh'
beforeEach(() => {
    captured.toast.mockClear()
    vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => vi.unstubAllGlobals())
describe('opt-in preservation after shared request handling', () => {
    it('preserves business rejection evidence without changing legacy callers', async () => {
        const response = { status: 200, config: {}, data: { status_code: 26130, status_message: 'conflict' } }
        await expect(captured.success!(response)).rejects.toBe('conflict')
        const rejected = await captured.success!({ ...response, config: { preserveError: true } }).catch(error => error)
        expect(rejected).toHaveProperty('response', { status: 200, data: response.data })
        expect(isDshRequestRejected(rejected)).toBe(true)
        expect(isDshRequestRejected({ response: { status: 200, data: { status_code: 26125 } } })).toBe(false)
        expect(isDshRequestRejected({ response: { status: 503 } })).toBe(false)
    })
    it('keeps the default null rejection and shared toast', async () => {
        const failure = {
            config: {},
            response: {
                status: 409,
                data: { status_code: 29003, status_message: 'conflict' },
            },
        }
        await expect(captured.failed!(failure)).rejects.toBeNull()
        expect(captured.toast).toHaveBeenCalledTimes(1)
    })
    it('preserves only opted-in transport evidence with the same toast', async () => {
        const failure = {
            config: { preserveError: true },
            response: {
                status: 409,
                data: { status_code: 29003, status_message: 'conflict' },
            },
        }
        await expect(captured.failed!(failure)).rejects.toBe(failure)
        expect(captured.toast).toHaveBeenCalledTimes(1)
    })
    it('retains cancellation behavior', async () => {
        const failure = { config: {}, code: 'ERR_CANCELED' }
        await expect(captured.failed!(failure)).rejects.toBe(failure)
        expect(captured.toast).not.toHaveBeenCalled()
    })
})


describe('desktop login after an expired browser session', () => {
    it.each([false, true])('preserves the authorization URL through 401 and SSO=%s', async (sso) => {
        const origin = 'http://192.168.106.109:13001'
        const target = origin + '/desktop-login?auth_id=3fef33bd-3b9d-4f93-830a-87052298ef79'
        const values = new Map<string, string>([['UUR_INFO', '1']])
        if (sso) values.set('THIRD_PARTY_LOGIN_URL', 'https://idp.example/login')
        vi.stubGlobal('localStorage', {
            getItem: (key: string) => values.get(key) ?? null,
            setItem: (key: string, value: string) => values.set(key, value),
            removeItem: (key: string) => values.delete(key),
        })
        const currentLocation = { href: target, origin, pathname: '/desktop-login' }
        vi.stubGlobal('location', currentLocation)
        // Startup captures the URL before UserContext performs its first request.
        rememberDesktopLoginReturnTo()
        await expect(captured.failed!({ response: { status: 401 } })).rejects.toBeTruthy()
        expect(currentLocation.href).toBe(sso ? 'https://idp.example/login' : '/')
        currentLocation.href = origin + '/'
        currentLocation.pathname = '/'
        // Both the local form and SSO landing use the same one-shot consumer.
        expect(consumeLoginReturnTo()).toBe(target)
        expect(consumeLoginReturnTo()).toBeNull()
    })
})
