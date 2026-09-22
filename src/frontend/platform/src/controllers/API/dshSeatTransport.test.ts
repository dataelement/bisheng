import { describe, expect, it, vi } from 'vitest'
vi.mock('@/components/bs-ui/toast/use-toast', () => ({ toast: vi.fn() }))
import request from '@/controllers/request'
import { commandDshSeat, isDshSeatLimitReached, saveDshSubjectPolicy } from './dsh'

describe('seat errors through the platform HTTP interceptor', () => {
    it('exposes a failed reassign receipt from a successful HTTP response', async () => {
        vi.stubGlobal('localStorage', { getItem: () => null })
        const previous = request.defaults.adapter
        const receipt = { operation_id: 'reassign-full', status: 'FAILED', result_code: 'seat_limit_reached' }
        request.defaults.adapter = async (config) => ({
            status: 200, statusText: 'OK', headers: {}, config,
            data: { status_code: 200, data: receipt },
        })
        try {
            const result = await commandDshSeat('20', '2', 'reassign', receipt.operation_id, 4)
            expect(result).toEqual(receipt)
            expect(isDshSeatLimitReached(result)).toBe(true)
        } finally {
            request.defaults.adapter = previous
            vi.unstubAllGlobals()
        }
    })
    it('preserves capacity rejection from an HTTP 200 business response', async () => {
        vi.stubGlobal('localStorage', { getItem: () => null })
        const previous = request.defaults.adapter
        request.defaults.adapter = async (config) => ({
            status: 200, statusText: 'OK', headers: {}, config,
            data: { status_code: 26112, status_message: 'DSH seat limit reached; contact an administrator' },
        })
        try {
            const failure = await saveDshSubjectPolicy(6, 'DEPARTMENT', 18, 1, {
                expected_version: 2, enabled: true, monthly_token_limit: 10000000,
            }).catch((error: unknown) => error)
            expect(isDshSeatLimitReached(failure)).toBe(true)
        } finally {
            request.defaults.adapter = previous
            vi.unstubAllGlobals()
        }
    })
})
