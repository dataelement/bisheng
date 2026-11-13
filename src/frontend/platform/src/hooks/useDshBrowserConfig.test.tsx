import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useDshBrowserConfig } from './useDshBrowserConfig'

const get = vi.hoisted(() => vi.fn())
vi.mock('@/controllers/API/dshSettings', () => ({ getDshBrowserConfig: get }))

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); get.mockReset() })
afterEach(() => { vi.useRealTimers() })

it('stops polling when DSH is not deployed', async () => {
    get.mockResolvedValue({ enabled: false, management_enabled: false })
    const { result } = renderHook(() => useDshBrowserConfig())
    await waitFor(() => expect(result.current.config?.management_enabled).toBe(false))
    vi.advanceTimersByTime(90000)
    window.dispatchEvent(new Event('focus'))
    expect(get).toHaveBeenCalledTimes(1)
})

it('keeps polling the runtime toggle when DSH is deployed', async () => {
    get.mockResolvedValue({ enabled: false, management_enabled: true })
    renderHook(() => useDshBrowserConfig())
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1))
    vi.advanceTimersByTime(30000)
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
})
