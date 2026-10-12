import { beforeEach, describe, expect, it, vi } from 'vitest'
import request from '@/controllers/request'
import { getDshAuditRecords } from './dshAudit'
vi.mock('@/controllers/request', () => ({ default: { get: vi.fn() } }))
const empty = { data: [], page_size: 20, has_more: false, next_cursor: null }
beforeEach(() => vi.resetAllMocks())
describe('audit read contract', () => {
    it('sends filters and cancellation through the request wrapper', async () => {
        vi.mocked(request.get).mockResolvedValue(empty)
        const signal = new AbortController().signal
        await expect(getDshAuditRecords({ limit: 20, status: 'FAILED' }, signal)).resolves.toEqual(empty)
        expect(request.get).toHaveBeenCalledWith('/api/v1/dsh/admin/audit-records', { params: { limit: 20, status: 'FAILED' }, signal })
    })
    it.each([null, { ...empty, has_more: true }, { ...empty, page_size: 200 }, { ...empty, data: [null] }])('rejects malformed history %j', async (value) => {
        vi.mocked(request.get).mockResolvedValue(value)
        await expect(getDshAuditRecords({ limit: 20 })).rejects.toThrow('Invalid DSH audit response')
    })
})
