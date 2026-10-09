import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../request', () => ({ default: request }))

beforeEach(() => {
    vi.resetModules()
    vi.resetAllMocks()
})

describe('citation API', () => {
    it('caches a fetched detail while retaining the wrapped request options', async () => {
        const api = await import('./citations')
        const detail = { citationId: 'document/1', type: 'rag' }
        request.get.mockResolvedValue(detail)

        expect(await api.getCitationDetail('document/1')).toEqual(detail)
        expect(await api.getCitationDetail('document/1')).toEqual(detail)
        expect(request.get).toHaveBeenCalledExactlyOnceWith(
            '/api/v1/citations/document%2F1', { silent: true },
        )
    })

    it.each(['expired', 'forbidden'] as const)(
        'preserves the %s access reason in resolved and rejected responses',
        async (reason) => {
            const api = await import('./citations')
            request.get.mockResolvedValueOnce({ status_code: 404, data: { reason } })
            request.get.mockRejectedValueOnce({ response: { data: { status_code: 404, reason } } })
            const flags = { citationExpired: reason === 'expired', citationForbidden: reason === 'forbidden' }

            await expect(api.getCitationDetail('resolved')).rejects.toMatchObject(flags)
            await expect(api.getCitationDetail('rejected')).rejects.toMatchObject(flags)
            expect(api.getCitationUnresolvedReason('resolved')).toBe(reason)
            expect(api.getCitationUnresolvedReason('rejected')).toBe(reason)
        },
    )

    it('coalesces batch requests and retains unresolved access reasons', async () => {
        const api = await import('./citations')
        const detail = { citationId: 'found', type: 'web' }
        request.post.mockResolvedValue({
            items: [detail], unresolved: [{ citationId: 'missing', reason: 'expired' }],
        })

        const replies = await Promise.all([
            api.resolveCitationDetails(['found', 'found', 'missing']),
            api.resolveCitationDetails(['missing', 'found']),
        ])
        expect(replies).toEqual([[detail, detail], [detail]])
        expect(request.post).toHaveBeenCalledExactlyOnceWith(
            '/api/v1/citations/resolve', { citationIds: ['found', 'missing'] }, { silent: true },
        )
        expect(api.getCitationUnresolvedReason('missing')).toBe('expired')
    })
})
