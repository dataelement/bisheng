import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AppUseLog from './index'

const mock = vi.hoisted(() => ({ filter: vi.fn(), page: vi.fn(), exportApi: vi.fn(), csv: vi.fn(), message: vi.fn() }))
vi.mock('@/contexts/locationContext', async () => ({ locationContext: (await import('react')).createContext({ appConfig: { isPro: true } }) }))
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: { user_name: 'Admin' } }) }))
vi.mock('@/controllers/API/log', () => ({ getAuditAppListApi: vi.fn(), exportCsvDataApi: mock.exportApi }))
vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({ useToast: () => ({ message: mock.message }) }))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
})
vi.mock('@/util/utils', async importOriginal => ({ ...(await importOriginal<typeof import('@/util/utils')>()), exportCsv: mock.csv }))
vi.mock('@/components/bs-comp/filterTableDataComponent/FilterByApp', () => ({ default: ({ onChange }: { onChange: (value: string[]) => void }) => <button onClick={() => onChange(['app-1'])}>Pick app</button> }))
vi.mock('@/components/bs-comp/filterTableDataComponent/FilterByUser', () => ({ default: () => null }))
vi.mock('@/components/bs-comp/filterTableDataComponent/FilterByUsergroup', () => ({ default: () => null }))
vi.mock('@/components/bs-comp/filterTableDataComponent/FilterByDate', () => ({ default: () => null }))
vi.mock('@/util/hook', () => ({ useTable: () => ({ page: 2, pageSize: 20, total: 2, loading: false, setPage: mock.page, filterData: mock.filter, data: [
    { id: 1, flow_type: 5, flow_name: 'Assistant', flow_id: 'app-1', chat_id: 'chat-1', user_groups: [{ name: 'Group' }], create_time: '2026-10-20T10:00:00', sensitive_status: 1 },
    { id: 2, flow_type: 15, chat_id: 'daily-1', user_groups: [], create_time: '2026-10-20T10:00:00', sensitive_status: 2 },
] }) }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
beforeEach(() => { mock.exportApi.mockResolvedValue({ data: [{ chat_id: 'chat-1', flow_name: 'Assistant', create_time: '2026-10-20T10:00:00', user_groups: [], messages: [{ message: '=formula', category: 'question', create_time: '2026-10-20T10:00:00', liked: 1, copied: true, sensitive_status: 1 }] }] }) })
it('preserves assistant/daily detail links, applied filters and reset', () => {
    render(<MemoryRouter><AppUseLog /></MemoryRouter>)
    expect(screen.getAllByRole('link', { name: 'lib.details' }).map(link => link.getAttribute('href'))).toEqual(['/log/chatlog/app-1/chat-1/5', '/log/chatlog/daily-1'])
    expect(screen.getByText('log.sensitivePass')).toBeVisible()
    expect(screen.getByText('log.sensitiveViolation')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Pick app' }))
    fireEvent.click(screen.getByRole('button', { name: 'log.searchButton' }))
    expect(mock.filter).toHaveBeenLastCalledWith(expect.objectContaining({ appName: ['app-1'] }))
    fireEvent.click(screen.getByRole('button', { name: 'log.resetButton' }))
    expect(mock.filter).toHaveBeenLastCalledWith(expect.objectContaining({ appName: [], feedback: '' }))
})
it('keeps the export loading state, default 60-day request and CSV formula protection', async () => {
    let resolveExport!: (value: unknown) => void
    mock.exportApi.mockReturnValueOnce(new Promise(resolve => { resolveExport = resolve }))
    render(<MemoryRouter><AppUseLog /></MemoryRouter>)
    const button = screen.getByRole('button', { name: 'log.exportButton' })
    fireEvent.click(button)
    expect(button).toBeDisabled()
    expect(mock.exportApi).toHaveBeenCalledWith(expect.objectContaining({ start_date: expect.stringMatching(/00:00:00$/), end_date: expect.stringMatching(/23:59:59$/) }))
    resolveExport({ data: [{ chat_id: 'chat-1', flow_name: 'Assistant', create_time: '2026-10-20T10:00:00', user_groups: [], messages: [{ message: '=formula', category: 'question', create_time: '2026-10-20T10:00:00', liked: 1, copied: true, sensitive_status: 1 }] }] })
    await waitFor(() => expect(mock.csv).toHaveBeenCalled())
    expect(mock.csv.mock.calls[0][0][1][7]).toBe("'=formula")
    await waitFor(() => expect(button).toBeEnabled())
})
