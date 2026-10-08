import { describe, expect, it, vi } from 'vitest'
vi.mock('@/controllers/request', () => ({ default: {} }))
import { isDshRequestRejected, isDshSeatLimitReached } from './dsh'
describe('seat capacity HTTP contract', () => {
    it('recognizes the DSH real HTTP error envelope', () => {
        expect(isDshSeatLimitReached({ response: { status: 403, data: { error: { code: 'seat_limit_reached' } } } })).toBe(true)
    })
    it('recognizes the direct business envelope rejected by silent requests', () => {
        expect(isDshSeatLimitReached({ status_code: 26112, status_message: 'DSH seat limit reached' })).toBe(true)
        expect(isDshSeatLimitReached({ status_code: 26101 })).toBe(false)
    })
    it('recognizes a failed durable allocation receipt', () => {
        expect(isDshSeatLimitReached({ code: 'seat_limit_reached' })).toBe(true)
        expect(isDshSeatLimitReached({ status: 'FAILED', result_code: 'seat_limit_reached' })).toBe(true)
        expect(isDshSeatLimitReached({ status: 'FAILED', result_code: 'license_expired' })).toBe(false)
        expect(isDshSeatLimitReached({ status: 'SUCCEEDED', result_code: null })).toBe(false)
    })
    it('distinguishes unrelated errors and supports the legacy envelope', () => {
        expect(isDshSeatLimitReached({ response: { data: { error: { code: 'license_expired' } } } })).toBe(false)
        expect(isDshSeatLimitReached({ response: { data: { status_code: 26112 } } })).toBe(true)
        expect(isDshSeatLimitReached(null)).toBe(false)
    })
    it('treats capacity rejection as definitive while retaining uncertain requests', () => {
        expect(isDshRequestRejected({ response: { status: 403, data: { error: { code: 'seat_limit_reached' } } } })).toBe(true)
        expect(isDshRequestRejected({ status_code: 26112 })).toBe(true)
        expect(isDshRequestRejected({ response: { status: 200, data: { status_code: 26112 } } })).toBe(true)
        expect(isDshRequestRejected(new Error('connection lost'))).toBe(false)
        expect(isDshRequestRejected({ response: { status: 503 } })).toBe(false)
        expect(isDshRequestRejected({ response: { status: 403, data: { error: { code: 'permission_denied' } } } })).toBe(false)
    })
})
