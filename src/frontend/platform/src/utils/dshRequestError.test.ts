import { describe, expect, it, vi } from 'vitest'
import { getDshRequestErrorKey } from './dshRequestError'

vi.mock('@/controllers/request', () => ({ default: {} }))

describe('DSH management error messages', () => {
    it.each([
        [26112, 'dsh.seatLimitGrantHelp'],
        [11001, 'api_errors:11001'],
        [26115, 'api_errors:26115'],
        [26125, 'api_errors:26125'],
        [26130, 'api_errors:26130'],
    ])('preserves business error %s in direct and HTTP envelopes', (code, key) => {
        expect(getDshRequestErrorKey({ status_code: code })).toBe(key)
        expect(getDshRequestErrorKey({ response: { data: { status_code: code } } })).toBe(key)
    })
    it.each([
        ['seat_limit_reached', 'dsh.seatLimitGrantHelp'],
        ['license_expired', 'api_errors:26115'],
        ['authorization_unavailable', 'api_errors:26125'],
        ['authorization_conflict', 'api_errors:26120'],
    ])('preserves %s in operation receipts and HTTP errors', (code, key) => {
        expect(getDshRequestErrorKey({ status: 'FAILED', result_code: code })).toBe(key)
        expect(getDshRequestErrorKey({ response: { data: { error: { code } } } })).toBe(key)
        expect(getDshRequestErrorKey(Object.assign(new Error('Operation failed'), { code }))).toBe(key)
    })
    it.each([null, new Error('Timeout'), { status_code: 500 }, { code: '__proto__' }, { code: 'constructor' }])(
        'leaves unknown failures to the caller fallback: %s', (error) => {
            expect(getDshRequestErrorKey(error)).toBeUndefined()
        },
    )
})
