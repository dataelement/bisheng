import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { type ReactNode } from 'react'
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
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const { result } = renderHook(() => useAppSecrets('app-a'), { wrapper })
    await waitFor(() => expect(result.current.data?.revision).toBe(1))
    await act(async () => { await result.current.save('COLOR', 'never-cache-this', 1) })
    expect(api.saveAppSecret).toHaveBeenCalledWith('app-a', 'COLOR', 'never-cache-this', 1)
    expect(api.rebuildAppSecrets).not.toHaveBeenCalled()
    expect(JSON.stringify(client.getQueryCache().getAll().map(query => ({ key: query.queryKey, state: query.state })))).not.toContain('never-cache-this')
    expect(client.getMutationCache().getAll()).toHaveLength(0)
  })
  it('an uncertain save is not automatically repeated', async () => {
    vi.mocked(api.saveAppSecret).mockRejectedValueOnce(new Error('network'))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const { result } = renderHook(() => useAppSecrets('app-a'), { wrapper })
    await waitFor(() => expect(result.current.data).toBeTruthy())
    await act(async () => { await expect(result.current.save('COLOR', 'draft', 1)).rejects.toThrow('network') })
    expect(api.saveAppSecret).toHaveBeenCalledTimes(1)
    expect(api.rebuildAppSecrets).not.toHaveBeenCalled()
  })
})
