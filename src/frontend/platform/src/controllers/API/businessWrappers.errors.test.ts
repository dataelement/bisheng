import { beforeEach, expect, it, vi } from 'vitest'
import request from '@/controllers/request'
import { getSelectableKnowledgeSpacesApi } from './knowledgeSpace'
import { checkAppEditPermission } from './flow'

vi.mock('@/controllers/request', () => ({ default: { get: vi.fn() } }))
beforeEach(() => vi.clearAllMocks())

it('preserves the original failure instead of presenting a partial knowledge-space union as complete', async () => {
    const error = new Error('Department spaces unavailable')
    vi.mocked(request.get).mockImplementation((url) => url.endsWith('/department')
        ? Promise.reject(error) : Promise.resolve([{ id: 1, name: 'Personal space' }]))
    await expect(getSelectableKnowledgeSpacesApi()).rejects.toBe(error)
})

it('stops editor initialization when the write-permission check rejects', async () => {
    const error = new Error('Access denied')
    vi.mocked(request.get).mockRejectedValueOnce(error)
    await expect(checkAppEditPermission('workflow-1', 10)).rejects.toBe(error)
})
