import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { EMPTY_ORG_SELECTION } from '@/controllers/API/log'
import SystemLog from './index'

const mock = vi.hoisted(() => ({ filter: vi.fn() }))
vi.mock('@/controllers/API/log', async (importOriginal) => ({
    ...(await importOriginal<typeof import('@/controllers/API/log')>()),
    getLogsApi: vi.fn(), getOperatorsApi: vi.fn().mockResolvedValue([]),
    getModulesApi: vi.fn().mockResolvedValue({ data: [{ value: '', name: 'Invalid module' }, { value: 'tenant', name: 'Tenant module' }] }),
    getActionsApi: vi.fn().mockResolvedValue([{ value: '', name: 'Invalid action' }, { value: 'tenant.mount', name: 'Mount tenant' }]),
    getActionsByModuleApi: vi.fn().mockResolvedValue([{ value: null, name: 'Invalid action' }, { value: 'tenant.mount', name: 'Mount tenant' }]),
    getAuditDepartmentsApi: vi.fn().mockResolvedValue({
        active: [{ id: 2, dept_id: 'BS@2', external_id: null, name: 'Sales', path_name: 'Root/Sales', parent_id: 1, tenant_id: 1, has_children: false }],
        archived: [], show_none: true, show_unrecorded: true,
    }),
}))
vi.mock('@/controllers/API/user', () => ({ getUserGroupsApi: vi.fn().mockResolvedValue([{ id: '', group_name: 'Invalid group' }, { id: null, group_name: 'Null group' }, { id: 'g1', group_name: 'Group 1' }]) }))
vi.mock('@/components/bs-ui/calendar/datePicker', () => ({ DatePicker: ({ placeholder, onChange }: { placeholder: string; onChange: (d: Date) => void }) => <button onClick={() => onChange(new Date('2026-10-20T00:00:00'))}>{placeholder}</button> }))
vi.mock('@/util/hook', () => ({
    useTable: () => ({
        page: 1, pageSize: 20, total: 3, loading: false, setPage: vi.fn(), filterData: mock.filter, data: [
            { id: 'audit-1', operator_name: 'Admin', create_time: '2026-10-20T10:00:00', action: 'tenant.mount', target_type: 'tenant', target_id: 'tenant-1', note: 'Audit note', operator_dept_id: 3, operator_dept_path: 'Root/Sales/East' },
            { id: 'audit-2', operator_name: 'system', operator_id: 0, create_time: '2026-10-20T10:00:00', event_type: 'update_sandbox_conf', operator_dept_id: -1 },
            { id: 'audit-3', operator_name: 'Old', create_time: '2026-10-20T10:00:00', event_type: 'user_login', operator_dept_id: null },
        ],
    }),
}))
afterEach(cleanup)

const renderPage = () => render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } } })}><SystemLog /></QueryClientProvider>,
)

it('preserves structured audit fields, valid filter options, date bounds and reset', async () => {
    renderPage()
    expect(screen.getByText('tenant-1')).toBeVisible()
    expect(screen.getByText('log.eventTypeEnum.tenantMount')).toBeVisible()
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'log.selectUserGroup' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Group 1' }))
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'log.systemModule' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Tenant module' }))
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'log.actionBehavior' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Mount tenant' }))
    fireEvent.click(screen.getByRole('button', { name: 'log.startDate' }))
    fireEvent.click(screen.getByRole('button', { name: 'log.endDate' }))
    fireEvent.click(screen.getByRole('button', { name: 'log.searchButton' }))
    await waitFor(() => expect(mock.filter).toHaveBeenLastCalledWith(expect.objectContaining({ groupId: 'g1', moduleId: 'tenant', action: 'tenant.mount', start: '2026-10-20 00:00:00', end: '2026-10-20 23:59:59' })))
    fireEvent.click(screen.getByRole('button', { name: 'log.resetButton' }))
    expect(mock.filter).toHaveBeenLastCalledWith({ userIds: [], groupId: '', start: undefined, end: undefined, moduleId: '', action: '', targetAppId: '', tenantId: undefined, org: EMPTY_ORG_SELECTION })
})

it('shows the organisation column with its three captions', () => {
    renderPage()
    expect(screen.getByText('Root/Sales/East')).toBeVisible()
    expect(screen.getByText('log.org.notApplicable')).toBeVisible()
    expect(screen.getByText('log.org.unrecorded')).toBeVisible()
    expect(screen.getByText('log.eventTypeEnum.update_sandbox_conf')).toBeVisible()
})

it('applies the organisation only when the query runs, and reset clears it', async () => {
    renderPage()
    mock.filter.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'log.org.placeholder' }))
    fireEvent.click(await screen.findByRole('checkbox', { name: /Sales/ }))
    fireEvent.click(screen.getByRole('button', { name: 'log.org.confirm' }))
    expect(mock.filter).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'log.searchButton' }))
    expect(mock.filter).toHaveBeenLastCalledWith(expect.objectContaining({ org: { ...EMPTY_ORG_SELECTION, deptIds: [2] } }))
    fireEvent.click(screen.getByRole('button', { name: 'log.resetButton' }))
    expect(mock.filter).toHaveBeenLastCalledWith(expect.objectContaining({ org: EMPTY_ORG_SELECTION }))
})
