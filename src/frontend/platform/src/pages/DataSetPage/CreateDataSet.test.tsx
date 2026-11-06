import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createPlatformQueryClient } from '@/queryClient'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import CreateDataSet from './CreateDataSet'

const mock = vi.hoisted(() => ({ create: vi.fn(), message: vi.fn(), read: vi.fn(), error: vi.fn() }))
vi.mock('@/controllers/API', () => ({ readFileLibDatabase: mock.read }))
vi.mock('@/controllers/API/finetune', () => ({ createDatasetApi: mock.create }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (p: Promise<unknown>) => p.catch(() => false), showApiError: mock.error }))
vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({ useToast: () => ({ message: mock.message }) }))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
})
vi.mock('@/components/bs-ui/upload/simple', () => ({ default: ({ onSuccess }: { onSuccess: (name: string, url: string) => void }) => <button onClick={() => onSuccess('sample.json', 'uploads/sample.json')}>Upload fixture</button> }))
vi.mock('@/util/utils', () => ({ downloadFile: vi.fn() }))
afterEach(cleanup)
beforeEach(() => {
    vi.clearAllMocks()
    mock.create.mockResolvedValue({})
    mock.read.mockReset().mockResolvedValue({ data: [{ id: 'qa-1', name: 'QA library' }], next_cursor: null })
})
function setup() {
    const ref = createRef<{ open: () => void }>()
    const onChange = vi.fn()
    render(<QueryClientProvider client={createPlatformQueryClient()}><CreateDataSet ref={ref} onChange={onChange} /></QueryClientProvider>)
    act(() => ref.current?.open())
    return { ref, onChange }
}
it('submits a local file using the existing dataset request schema', async () => {
    const { onChange } = setup()
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Dataset' } })
    fireEvent.click(screen.getByText('Upload fixture'))
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    await waitFor(() => expect(mock.create).toHaveBeenCalledWith({ name: 'Dataset', files: 'uploads/sample.json', qa_list: [] }))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
})
it('clears a previous file when switching to QA and submits only selected libraries', async () => {
    setup()
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'QA dataset' } })
    fireEvent.click(screen.getByText('Upload fixture'))
    fireEvent.click(screen.getByRole('radio', { name: 'dataset.importFromQa' }))
    expect(screen.queryByText('Upload fixture')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    expect(mock.create).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('combobox', { name: 'dataset.selectQaKnowledgeLib' }))
    fireEvent.click(await screen.findByRole('option', { name: 'QA library' }))
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    await waitFor(() => expect(mock.create).toHaveBeenCalledWith({ name: 'QA dataset', files: '', qa_list: ['qa-1'] }))
})

it('loads further QA pages and preserves selections when searching', async () => {
    mock.read.mockResolvedValueOnce({ data: [{ id: 'qa-1', name: 'First QA' }], next_cursor: 'page-2' })
        .mockResolvedValueOnce({ data: [{ id: 'qa-1', name: 'First QA' }, { id: 'qa-2', name: 'Second QA' }], next_cursor: null })
        .mockResolvedValueOnce({ data: [{ id: 'qa-3', name: 'Search QA' }], next_cursor: null })
    setup()
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'QA dataset' } })
    fireEvent.click(screen.getByRole('radio', { name: 'dataset.importFromQa' }))
    const select = screen.getByRole('combobox', { name: 'dataset.selectQaKnowledgeLib' })
    fireEvent.click(select)
    fireEvent.click(await screen.findByRole('option', { name: 'First QA' }))
    expect(screen.getByRole('combobox')).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'sharedUi.remove' }))
    expect(screen.getByRole('combobox')).toHaveFocus()
    expect(screen.getByRole('option', { name: 'First QA' })).toHaveAttribute('aria-selected', 'false')
    fireEvent.click(screen.getByRole('option', { name: 'First QA' }))

    const panel = screen.getByRole('listbox').parentElement!
    fireEvent.scroll(panel)
    await screen.findByRole('option', { name: 'Second QA' })
    expect(screen.getAllByRole('option', { name: 'First QA' })).toHaveLength(1)
    expect(mock.read).toHaveBeenNthCalledWith(2, { cursor: 'page-2', pageSize: 60, name: '', type: 1, action: 'use' })
    fireEvent.click(screen.getByRole('option', { name: 'Second QA' }))

    fireEvent.change(select, { target: { value: 'Search' } })
    fireEvent.click(await screen.findByRole('option', { name: 'Search QA' }))
    expect(mock.read).toHaveBeenLastCalledWith({ cursor: null, pageSize: 60, name: 'Search', type: 1, action: 'use' })
    fireEvent.keyDown(select, { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    await waitFor(() => expect(mock.create).toHaveBeenCalledWith({ name: 'QA dataset', files: '', qa_list: ['qa-1', 'qa-2', 'qa-3'] }))
})

it('keeps the newest search result when an older request finishes later', async () => {
    let resolveOld: (value: { data: { id: string; name: string }[]; next_cursor: null }) => void = () => {}
    mock.read.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
        .mockResolvedValueOnce({ data: [{ id: 'qa-new', name: 'Current result' }], next_cursor: null })
    setup()
    fireEvent.click(screen.getByRole('radio', { name: 'dataset.importFromQa' }))
    const select = screen.getByRole('combobox', { name: 'dataset.selectQaKnowledgeLib' })
    fireEvent.click(select)
    fireEvent.change(select, { target: { value: 'Current' } })
    await screen.findByRole('option', { name: 'Current result' })
    await act(async () => resolveOld({ data: [{ id: 'qa-old', name: 'Stale result' }], next_cursor: null }))
    expect(screen.getByRole('option', { name: 'Current result' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Stale result' })).not.toBeInTheDocument()
})

it('reports a failed QA load and allows retry by reopening the selector', async () => {
    const error = new Error('QA unavailable')
    mock.read.mockRejectedValueOnce(error)
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
        setup()
        fireEvent.click(screen.getByRole('radio', { name: 'dataset.importFromQa' }))
        const select = screen.getByRole('combobox', { name: 'dataset.selectQaKnowledgeLib' })
        fireEvent.click(select)
        await waitFor(() => expect(mock.error).toHaveBeenCalledWith(error))
        fireEvent.keyDown(select, { key: 'Escape' })
        fireEvent.click(select)
        expect(await screen.findByRole('option', { name: 'QA library' })).toBeInTheDocument()
    } finally {
        consoleError.mockRestore()
    }
})
it('resets the import mode and draft when reopened', () => {
    const { ref } = setup()
    fireEvent.click(screen.getByRole('radio', { name: 'dataset.importFromQa' }))
    fireEvent.click(screen.getByRole('button', { name: 'cancel' }))
    act(() => ref.current?.open())
    expect(screen.getByRole('radio', { name: 'dataset.localImport' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('textbox')).toHaveValue('')
})

it('retains the draft after a failed create and allows a successful retry', async () => {
    mock.create.mockRejectedValueOnce(new Error('Create failed'))
    const { onChange } = setup()
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Retry dataset' } })
    fireEvent.click(screen.getByText('Upload fixture'))
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    await waitFor(() => expect(mock.create).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('textbox')).toHaveValue('Retry dataset')
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1))
})
