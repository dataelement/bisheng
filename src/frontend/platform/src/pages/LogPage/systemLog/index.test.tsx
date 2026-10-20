import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import SystemLog from './index'

const mock = vi.hoisted(() => ({ filter: vi.fn() }))
vi.mock('@/controllers/API/log', () => ({
    getLogsApi: vi.fn(), getOperatorsApi: vi.fn().mockResolvedValue([]),
    getModulesApi: vi.fn().mockResolvedValue({ data: [{ value: '', name: 'Invalid module' }, { value: 'tenant', name: 'Tenant module' }] }),
    getActionsApi: vi.fn().mockResolvedValue([{ value: '', name: 'Invalid action' }, { value: 'tenant.mount', name: 'Mount tenant' }]),
    getActionsByModuleApi: vi.fn().mockResolvedValue([{ value: null, name: 'Invalid action' }, { value: 'tenant.mount', name: 'Mount tenant' }]),
}))
vi.mock('@/controllers/API/user', () => ({ getUserGroupsApi: vi.fn().mockResolvedValue([{ id: '', group_name: 'Invalid group' }, { id: null, group_name: 'Null group' }, { id: 'g1', group_name: 'Group 1' }]) }))
vi.mock('@/components/bs-ui/select/multi', () => ({ default: () => null }))
vi.mock('@/components/bs-ui/calendar/datePicker', () => ({ DatePicker: ({ placeholder, onChange }: { placeholder: string; onChange: (d: Date) => void }) => <button onClick={() => onChange(new Date('2026-10-20T00:00:00'))}>{placeholder}</button> }))
vi.mock('@/util/hook', () => ({ useTable: () => ({ page: 1, pageSize: 20, total: 1, loading: false, setPage: vi.fn(), filterData: mock.filter, data: [{ id: 'audit-1', operator_name: 'Admin', create_time: '2026-10-20T10:00:00', action: 'tenant.mount', target_type: 'tenant', target_id: 'tenant-1', note: 'Audit note' }] }) }))
afterEach(cleanup)
it('preserves structured audit fields, valid filter options, date bounds and reset', async () => {
    render(<SystemLog />)
    expect(screen.getByText('tenant-1')).toBeVisible()
    expect(screen.getByText('log.eventTypeEnum.tenantMount')).toBeVisible()
    fireEvent.keyDown(screen.getAllByRole('combobox')[0], { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Group 1' }))
    fireEvent.keyDown(screen.getAllByRole('combobox')[1], { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Tenant module' }))
    fireEvent.keyDown(screen.getAllByRole('combobox')[2], { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Mount tenant' }))
    fireEvent.click(screen.getByRole('button', { name: 'log.startDate' }))
    fireEvent.click(screen.getByRole('button', { name: 'log.endDate' }))
    fireEvent.click(screen.getByRole('button', { name: 'log.searchButton' }))
    await waitFor(() => expect(mock.filter).toHaveBeenLastCalledWith(expect.objectContaining({ groupId: 'g1', moduleId: 'tenant', action: 'tenant.mount', start: '2026-10-20 00:00:00', end: '2026-10-20 23:59:59' })))
    fireEvent.click(screen.getByRole('button', { name: 'log.resetButton' }))
    expect(mock.filter).toHaveBeenLastCalledWith({ userIds: [], groupId: '', start: undefined, end: undefined, moduleId: '', action: '' })
})
