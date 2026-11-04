import { normalizeApiError } from '@bisheng/api-client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createContext } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useEditorDashboardStore } from '@/store/dashboardStore'
import type { Dashboard } from '../../types/dataConfig'
import { EditorHeader } from './EditorHeader'

const mock = vi.hoisted(() => ({ save: vi.fn(), publish: vi.fn(), navigate: vi.fn(), notice: vi.fn() }))
vi.mock('@/controllers/API/dashboard', () => ({ updateDashboard: mock.save, publishDashboard: mock.publish }))
vi.mock('react-router-dom', () => ({ useNavigate: () => mock.navigate }))
vi.mock('@/contexts/userContext', () => ({ userContext: createContext({ user: {} }) }))
vi.mock('./ComponentPicker', () => ({ default: ({ children }: { children: React.ReactNode }) => children }))
vi.mock('@bisheng/ui', async (importOriginal) => ({
    ...await importOriginal<typeof import('@bisheng/ui')>(), notification: { open: mock.notice },
}))

const dashboard: Dashboard = {
    id: '7', title: 'Draft board', description: '', status: 'draft', dashboard_type: 'custom',
    components: [], layout_config: { layouts: [] }, style_config: { theme: 'light' },
    create_time: '2026-10-22T10:00:00', update_time: '2026-10-22T10:00:00',
    is_default: false, user_name: 'Editor', write: true,
}
beforeEach(() => {
    vi.clearAllMocks()
    mock.save.mockResolvedValue(dashboard)
    mock.publish.mockResolvedValue(null)
    useEditorDashboardStore.setState({ currentDashboard: dashboard, hasUnsavedChanges: true, layouts: [], lastChangeTime: Date.now(), isSaving: false })
})
afterEach(() => { cleanup(); useEditorDashboardStore.getState().reset() })

function setup() {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } }, logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() } })
    render(<QueryClientProvider client={client}><EditorHeader dashboard={dashboard} dashboardId="7" /></QueryClientProvider>)
    return client
}

it('preserves unsaved changes and unlocks save after a rejected save without publishing or navigating', async () => {
    mock.save.mockRejectedValueOnce(normalizeApiError(new Error('Save failed'), { message: 'Save failed' }))
    const client = setup()
    fireEvent.click(screen.getByRole('button', { name: 'saveAndPublish' }))
    await waitFor(() => expect(mock.notice).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' })))
    expect(mock.publish).not.toHaveBeenCalled()
    expect(mock.navigate).not.toHaveBeenCalled()
    expect(useEditorDashboardStore.getState().hasUnsavedChanges).toBe(true)
    expect(useEditorDashboardStore.getState().currentDashboard?.title).toBe('Draft board')
    expect(screen.getByRole('button', { name: 'saveAndPublish' })).toBeEnabled()
    expect(mock.notice.mock.calls.filter(([notice]) => notice.type === 'error')).toHaveLength(1)
    client.clear()
})

it('does not navigate when publishing fails after a successful save and permits retry', async () => {
    mock.publish.mockRejectedValueOnce(normalizeApiError(new Error('Publish failed'), { message: 'Publish failed' }))
    const client = setup()
    fireEvent.click(screen.getByRole('button', { name: 'saveAndPublish' }))
    await waitFor(() => expect(mock.notice).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' })))
    expect(mock.navigate).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('button', { name: 'saveAndPublish' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'saveAndPublish' }))
    await waitFor(() => expect(mock.navigate).toHaveBeenCalledWith('/dashboard?selected=7'))
    expect(mock.save.mock.invocationCallOrder[0]).toBeLessThan(mock.publish.mock.invocationCallOrder[0])
    expect(mock.publish).toHaveBeenCalledTimes(2)
    client.clear()
})
