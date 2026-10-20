import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import Tasks from './index'

const mock = vi.hoisted(() => ({ create: vi.fn().mockResolvedValue({ id: 1 }), reload: vi.fn() }))
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: { role: 'admin' } }) }))
vi.mock('@/controllers/API/assistant', () => ({ getChatOnlineApi: vi.fn().mockResolvedValue({ list: [{ id: 'app-1', name: 'App', count: 5 }], nextCursor: null }) }))
vi.mock('@/controllers/API/log', () => ({ createMarkApi: mock.create, getMarksApi: vi.fn(), deleteMarkApi: vi.fn() }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (p: Promise<unknown>) => p }))
vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({ useToast: () => ({ message: vi.fn() }) }))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
})
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }))
vi.mock('@/components/bs-ui/select/multi', () => ({ default: ({ onChange }: { onChange: (value: { value: string }[]) => void }) => <button onClick={() => onChange([{ value: 'app-1' }])}>Select app</button> }))
vi.mock('@/components/bs-comp/selectComponent/Users', () => ({ default: ({ onChange }: { onChange: (value: { value: string }[]) => void }) => <button onClick={() => onChange([{ value: 'user-1' }])}>Select annotator</button> }))
vi.mock('@/util/hook', () => ({ useTable: () => ({ page: 1, pageSize: 20, total: 1, setPage: vi.fn(), filterData: vi.fn(), reload: mock.reload, data: [{ id: 7, status: 3, create_time: '2026-10-20T10:00:00', create_user: 'Admin', mark_process: ['Alice 1/5'] }] }) }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('keeps the task link and requires applications plus annotators before creation', async () => {
    render(<MemoryRouter><Tasks /></MemoryRouter>)
    expect(screen.getByRole('link', { name: 'label.view' })).toHaveAttribute('href', '/label/7')
    fireEvent.click(screen.getByRole('button', { name: 'label.createTask' }))
    expect(screen.getByRole('button', { name: 'label.create' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Select app' }))
    expect(screen.getByRole('button', { name: 'label.create' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Select annotator' }))
    fireEvent.click(screen.getByRole('button', { name: 'label.create' }))
    await waitFor(() => expect(mock.create).toHaveBeenCalledWith({ app_list: ['app-1'], user_list: ['user-1'] }))
    await waitFor(() => expect(mock.reload).toHaveBeenCalledTimes(1))
})
