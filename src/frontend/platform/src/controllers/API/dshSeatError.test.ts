import { describe, expect, it, vi } from 'vitest'
vi.mock('@/controllers/request', () => ({ default: {} }))
import { isDshSeatLimitReached } from './dsh'
describe('seat capacity HTTP contract', () => {
    it('recognizes the DSH real HTTP error envelope', () => {
        expect(isDshSeatLimitReached({ response: { status: 403, data: { error: { code: 'seat_limit_reached' } } } })).toBe(true)
    })
    it('recognizes a failed durable allocation receipt', () => {
        expect(isDshSeatLimitReached({ code: 'seat_limit_reached' })).toBe(true)
    })
    it('distinguishes unrelated errors and supports the legacy envelope', () => {
        expect(isDshSeatLimitReached({ response: { data: { error: { code: 'license_expired' } } } })).toBe(false)
        expect(isDshSeatLimitReached({ response: { data: { status_code: 26112 } } })).toBe(true)
        expect(isDshSeatLimitReached(null)).toBe(false)
    })
})
