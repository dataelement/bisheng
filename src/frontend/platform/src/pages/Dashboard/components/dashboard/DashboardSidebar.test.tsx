import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { DashboardSidebar } from './DashboardSidebar'

const mock = vi.hoisted(() => ({
    user: { role: 'user', is_child_admin: true, web_menu: [] as string[] },
    create: vi.fn().mockResolvedValue({ id: '42' }),
    select: vi.fn(),
}))
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: mock.user }) }))
vi.mock('@/components/bs-comp/permission/PermissionDialog', () => ({ PermissionDialog: () => null }))
vi.mock('./DashboardListItem', () => ({ DashboardListItem: () => null }))
vi.mock('@/controllers/API/dashboard', () => ({ createDashboard: mock.create, copyDashboard: vi.fn(), deleteDashboard: vi.fn() }))

function setup() {
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><DashboardSidebar dashboards={[]} selectedId={null} isCollapsed={false}
            setIsCollapsed={vi.fn()} onSelect={mock.select} onRename={vi.fn()} onDefault={vi.fn()} onShare={vi.fn()} />
        </MemoryRouter>
    </QueryClientProvider>)
}

afterEach(() => { cleanup(); vi.clearAllMocks(); mock.user.is_child_admin = true })

it('lets a child administrator create without a personal menu grant', async () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'addDashboard' }))
    await waitFor(() => expect(mock.create).toHaveBeenCalled())
    await waitFor(() => expect(mock.select).toHaveBeenCalledWith('42'))
})

it('keeps creation hidden for an ordinary user without the menu grant', () => {
    mock.user.is_child_admin = false
    setup()
    expect(screen.queryByRole('button', { name: 'addDashboard' })).not.toBeInTheDocument()
})
