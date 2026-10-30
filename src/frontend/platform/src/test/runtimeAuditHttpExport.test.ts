import { afterEach, expect, it, vi } from 'vitest'
import { createRuntimeAuditExport } from '@/controllers/API/runtimeAudit'

const post = vi.hoisted(() => vi.fn())
vi.mock('@/controllers/request', () => ({ default: { post } }))
afterEach(() => vi.unstubAllGlobals())

it('sends export requests on HTTP where randomUUID is unavailable', async () => {
  vi.stubGlobal('crypto', { getRandomValues: (bytes: Uint8Array) => bytes.fill(7) })
  post.mockResolvedValue({ export_id: 'job', status: 'pending' })
  await expect(createRuntimeAuditExport('snapshot', 3)).resolves.toEqual({ export_id: 'job', status: 'pending' })
  expect(post).toHaveBeenCalledWith('/api/v1/app-runtime-audit/exports', {
    snapshot_id: 'snapshot', tenant_id: 3,
    request_id: expect.stringMatching(/^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/i),
  })
})
