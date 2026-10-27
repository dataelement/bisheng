import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { publishDashboard } from '@/controllers/API/dashboard'
import { DashboardQueryKey, DashboardsQueryKey, usePublishDashboard } from './hook'

vi.mock('@/controllers/API/dashboard', () => ({ publishDashboard: vi.fn(async () => ({})) }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it.each([false, true])('publishes directly with a numeric editor cache and list present: %s', async (withList) => {
    const { QueryClient, QueryClientProvider } = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query')
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const board = { id: '7', title: 'Board', status: 'draft' }
    client.setQueryData([DashboardQueryKey, 7], board)
    client.setQueryData([DashboardQueryKey, 'other'], { ...board, id: 'other' })
    if (withList) {
        client.setQueryData([DashboardQueryKey, '7'], board)
        client.setQueryData([DashboardsQueryKey], [board])
    }
    const { result } = renderHook(() => usePublishDashboard(), {
        wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    })
    await act(async () => { await result.current.publishAsync('7', false) })
    expect(publishDashboard).toHaveBeenLastCalledWith('7', 'published')
    expect(client.getQueryData([DashboardQueryKey, 7])).toMatchObject({ status: 'published' })
    expect(client.getQueryData([DashboardQueryKey, 'other'])).toMatchObject({ status: 'draft' })
    if (withList) {
        expect(client.getQueryData([DashboardQueryKey, '7'])).toMatchObject({ status: 'published' })
        expect(client.getQueryData([DashboardsQueryKey])).toEqual([expect.objectContaining({ status: 'published' })])
    } else expect(client.getQueryData([DashboardsQueryKey])).toBeUndefined()
    await act(async () => { await result.current.publishAsync('7', true) })
    expect(client.getQueryData([DashboardQueryKey, 7])).toMatchObject({ status: 'draft' })
    client.clear()
})
