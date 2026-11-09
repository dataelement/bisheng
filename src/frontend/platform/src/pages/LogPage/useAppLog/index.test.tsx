import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { EMPTY_ORG_SELECTION } from '@/controllers/API/log'
import AppUseLog from './index'

const mock = vi.hoisted(() => {
    const rows = [
        { id: 1, flow_type: 5, flow_name: 'Assistant', flow_id: 'app-1', chat_id: 'chat-1', user_groups: [{ name: 'Group' }], create_time: '2026-10-20T10:00:00', sensitive_status: 1 },
        { id: 2, flow_type: 15, chat_id: 'daily-1', user_groups: [], create_time: '2026-10-20T10:00:00', sensitive_status: 2, operator_dept_id: 3, operator_dept_path: 'Root/Sales' },
        { id: 3, flow_type: 20, flow_name: 'Space QA', chat_id: 'space-1', user_groups: [], create_time: '2026-10-20T10:00:00', sensitive_status: 1, operator_dept_id: -1 },
    ]
    return { filter: vi.fn(), page: vi.fn(), exportApi: vi.fn(), csv: vi.fn(), message: vi.fn(), rows, initialRows: rows }
})
vi.mock('@/contexts/locationContext', async () => ({ locationContext: (await import('react')).createContext({ appConfig: { isPro: true } }) }))
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: { user_name: 'Admin' } }) }))
vi.mock('@/controllers/API/log', async (importOriginal) => ({
    ...(await importOriginal<typeof import('@/controllers/API/log')>()),
    getAuditAppListApi: vi.fn(), exportCsvDataApi: mock.exportApi,
    getAuditSessionUsersApi: vi.fn().mockResolvedValue([{ user_id: 7, user_name: 'Alice' }]),
}))
vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({ useToast: () => ({ message: mock.message }) }))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
})
vi.mock('@/util/utils', async importOriginal => ({ ...(await importOriginal<typeof import('@/util/utils')>()), exportCsv: mock.csv }))
vi.mock('@/components/bs-comp/filterTableDataComponent/FilterByApp', () => ({ default: ({ onChange }: { onChange: (value: string[]) => void }) => <button onClick={() => onChange(['app-1'])}>Pick app</button> }))
vi.mock('@/components/bs-comp/filterTableDataComponent/FilterByUsergroup', () => ({ default: () => null }))
vi.mock('@/components/bs-comp/filterTableDataComponent/FilterByDate', () => ({ default: () => null }))
vi.mock('@/util/hook', () => ({ useTable: () => ({ page: 2, pageSize: 20, total: mock.rows.length, loading: false, loaded: true, setPage: mock.page, filterData: mock.filter, data: mock.rows }) }))
afterEach(() => { cleanup(); vi.clearAllMocks(); mock.rows = mock.initialRows })
beforeEach(() => { mock.exportApi.mockResolvedValue({ data: [{ chat_id: 'chat-1', flow_name: 'Assistant', create_time: '2026-10-20T10:00:00', user_groups: [], messages: [{ message: '=formula', category: 'question', create_time: '2026-10-20T10:00:00', liked: 1, copied: true, sensitive_status: 1 }] }] }) })
it('preserves assistant/daily detail links, applied filters and reset', () => {
    render(<MemoryRouter><AppUseLog /></MemoryRouter>)
    expect(screen.getAllByRole('button')[0]).toHaveAccessibleName('log.org.placeholder')
    expect(screen.getAllByRole('link', { name: 'lib.details' }).map(link => link.getAttribute('href'))).toEqual(['/log/chatlog/app-1/chat-1/5', '/log/chatlog/daily-1', '/log/chatlog/space-1'])
    expect(screen.getAllByText('log.sensitivePass')[0]).toBeVisible()
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
    const [header, line] = mock.csv.mock.calls[0][0]
    expect(header.slice(0, 7)).toEqual(['log.csvHeaders.sessionId', 'log.csvHeaders.appName', 'log.csvHeaders.usageType', 'log.csvHeaders.sessionCreationTime', 'log.csvHeaders.userName', 'log.csvHeaders.org', 'log.csvHeaders.userGroup'])
    expect(line[5]).toBe('log.org.unrecorded')
    expect(line[9]).toBe("'=formula")
    await waitFor(() => expect(button).toBeEnabled())
})
it('shows an empty state when the query returns no rows', () => {
    mock.rows = []
    render(<MemoryRouter><AppUseLog /></MemoryRouter>)
    expect(screen.getByRole('status')).toHaveTextContent('log.emptyTitle')
    expect(screen.getByText('log.emptyHint')).toBeVisible()
    expect(screen.getByText('log.appName')).toBeVisible()
})
it('shows the organisation column and applies usage type and organisation only on query', async () => {
    render(<MemoryRouter><AppUseLog /></MemoryRouter>)
    expect(screen.getByText('Root/Sales')).toBeVisible()
    expect(screen.getByText('log.org.notApplicable')).toBeVisible()
    expect(screen.getByText('Space QA')).toBeVisible()
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'log.usageType.label' }), { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'log.usageType.task' }))
    expect(mock.filter).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'log.searchButton' }))
    expect(mock.filter).toHaveBeenLastCalledWith(expect.objectContaining({ usageType: 'task', org: EMPTY_ORG_SELECTION }))
    fireEvent.click(screen.getByRole('button', { name: 'log.resetButton' }))
    expect(mock.filter).toHaveBeenLastCalledWith(expect.objectContaining({ usageType: '', userId: null }))
})
