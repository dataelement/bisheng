import { beforeEach, describe, expect, it, vi } from 'vitest'
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
import { isDshRequestRejected } from './API/dsh'
beforeEach(() => {
    captured.toast.mockClear()
    vi.spyOn(console, 'error').mockImplementation(() => {})
})
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
