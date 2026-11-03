import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAppSecrets } from './useAppSecrets'
import * as api from '@/controllers/API/appSecrets'

vi.mock('@/controllers/API/appSecrets', () => ({ getAppSecrets: vi.fn(), saveAppSecret: vi.fn(), deleteAppSecret: vi.fn(), rebuildAppSecrets: vi.fn() }))
const state = { revision: 1, updated_at: null, items: [], runtime: { comparison: 'different', saved_revision: 1, running_operation_id: 'old', running_version_id: 'v1', route_epoch: 3, changed_names: ['COLOR'], rebuild_operation: null } }

describe('manual environment apply', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getAppSecrets).mockResolvedValue(state as api.AppSecrets)
    vi.mocked(api.saveAppSecret).mockResolvedValue({ revision: 2, present: true, updated_at: '' })
  })
  it('saving calls no rebuild and leaves no plaintext in query/mutation cache', async () => {
    // This must render under the 130 shell without a TanStack provider.
    const { result } = renderHook(() => useAppSecrets('app-a'))
    await waitFor(() => expect(result.current.data?.revision).toBe(1))
    await act(async () => { await result.current.save('COLOR', 'never-cache-this', 1) })
    expect(api.saveAppSecret).toHaveBeenCalledWith('app-a', 'COLOR', 'never-cache-this', 1)
    expect(api.rebuildAppSecrets).not.toHaveBeenCalled()
    expect(JSON.stringify(result.current)).not.toContain('never-cache-this')
  })
  it('an uncertain save is not automatically repeated', async () => {
    vi.mocked(api.saveAppSecret).mockRejectedValueOnce(new Error('network'))
    // This must render under the 130 shell without a TanStack provider.
    const { result } = renderHook(() => useAppSecrets('app-a'))
    await waitFor(() => expect(result.current.data).toBeTruthy())
    await act(async () => { await expect(result.current.save('COLOR', 'draft', 1)).rejects.toThrow('network') })
    expect(api.saveAppSecret).toHaveBeenCalledTimes(1)
    expect(api.rebuildAppSecrets).not.toHaveBeenCalled()
  })
  it('ignores a late response after switching applications', async () => {
    let finishOld!: (value: api.AppSecrets) => void
    vi.mocked(api.getAppSecrets).mockImplementation((appId) => appId === 'app-a'
      ? new Promise(resolve => { finishOld = resolve })
      : Promise.resolve({ ...state, revision: 8 } as api.AppSecrets))
    const { result, rerender } = renderHook(({ appId }) => useAppSecrets(appId), { initialProps: { appId: 'app-a' } })
    rerender({ appId: 'app-b' })
    await waitFor(() => expect(result.current.data?.revision).toBe(8))
    await act(async () => { finishOld({ ...state, revision: 2 } as api.AppSecrets) })
    expect(result.current.data?.revision).toBe(8)
    expect(result.current.loading).toBe(false)
  })
})
