import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import EvaluationCreate from './EvaluationCreate'

const mock = vi.hoisted(() => ({ create: vi.fn(), apps: vi.fn(), toast: vi.fn() }))
vi.mock('@/contexts/tabsContext', async () => ({ TabsContext: (await import('react')).createContext({ flow: null }) }))
vi.mock('./PromptCom', () => ({ default: () => <div>Prompt editor</div> }))
vi.mock('@/controllers/API/evaluate', () => ({ createEvaluationApi: mock.create }))
vi.mock('@/controllers/API/flow', () => ({ getAppsApi: mock.apps }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (p: Promise<unknown>) => p }))
vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({ useToast: () => ({ toast: mock.toast }) }))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
})
afterEach(cleanup)
beforeEach(() => {
    vi.clearAllMocks()
    mock.create.mockResolvedValue({})
    mock.apps.mockResolvedValue({ data: [
        { id: null, name: 'Invalid app' }, { id: '', name: 'Empty app' },
        { id: 'app-1', name: 'Workflow', version_list: [{ id: '', name: 'Invalid version' }, { id: null, name: 'Null version' }, { id: 'v1', name: 'Version 1' }] },
    ] })
})
async function selectWorkflow() {
    fireEvent.keyDown(screen.getAllByRole('combobox')[0], { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'build.workFlow' }))
    await waitFor(() => expect(mock.apps).toHaveBeenCalled())
    fireEvent.keyDown(screen.getAllByRole('combobox')[1], { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Workflow' }))
    fireEvent.keyDown(screen.getAllByRole('combobox')[2], { key: 'ArrowDown' })
    fireEvent.click(await screen.findByRole('option', { name: 'Version 1' }))
}
it('filters empty backend IDs and submits the original multipart evaluation payload', async () => {
    render(<MemoryRouter><EvaluationCreate /></MemoryRouter>)
    await selectWorkflow()
    const file = new File(['question,answer\nHello,World'], 'sample.csv', { type: 'text/csv' })
    fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [file] } })
    await screen.findByText('sample.csv')
    fireEvent.click(screen.getByRole('button', { name: 'evaluation.create' }))
    await waitFor(() => expect(mock.create).toHaveBeenCalledTimes(1))
    const form = mock.create.mock.calls[0][0] as FormData
    expect(form.get('exec_type')).toBe('workflow')
    expect(form.get('unique_id')).toBe('app-1')
    expect(form.get('version')).toBe('v1')
    expect(form.get('file')).toBe(file)
    expect(form.get('prompt')).toBeTruthy()
})
it('retains required selection and file validation before submitting', async () => {
    render(<MemoryRouter><EvaluationCreate /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: 'evaluation.create' }))
    expect(mock.toast).toHaveBeenLastCalledWith(expect.objectContaining({ description: 'evaluation.enterExecType' }))
    await selectWorkflow()
    fireEvent.click(screen.getByRole('button', { name: 'evaluation.create' }))
    expect(mock.toast).toHaveBeenLastCalledWith(expect.objectContaining({ description: 'evaluation.enterFile' }))
    expect(mock.create).not.toHaveBeenCalled()
})
