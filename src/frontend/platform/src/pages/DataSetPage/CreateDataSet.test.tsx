import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import CreateDataSet from './CreateDataSet'

const mock = vi.hoisted(() => ({ create: vi.fn(), message: vi.fn() }))
vi.mock('@/controllers/API/finetune', () => ({ createDatasetApi: mock.create }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (p: Promise<unknown>) => p }))
vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({ useToast: () => ({ message: mock.message }) }))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
})
vi.mock('@/components/bs-ui/upload/simple', () => ({ default: ({ onSuccess }: { onSuccess: (name: string, url: string) => void }) => <button onClick={() => onSuccess('sample.json', 'uploads/sample.json')}>Upload fixture</button> }))
vi.mock('@/components/bs-comp/selectComponent/knowledge', () => ({ default: ({ onChange }: { onChange: (value: { value: string }[]) => void }) => <button onClick={() => onChange([{ value: 'qa-1' }])}>Select QA fixture</button> }))
vi.mock('@/util/utils', () => ({ downloadFile: vi.fn() }))
afterEach(cleanup)
beforeEach(() => { vi.clearAllMocks(); mock.create.mockResolvedValue({}) })
function setup() {
    const ref = createRef<{ open: () => void }>()
    const onChange = vi.fn()
    render(<CreateDataSet ref={ref} onChange={onChange} />)
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
    fireEvent.click(screen.getByText('Select QA fixture'))
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }))
    await waitFor(() => expect(mock.create).toHaveBeenCalledWith({ name: 'QA dataset', files: '', qa_list: ['qa-1'] }))
})
it('resets the import mode and draft when reopened', () => {
    const { ref } = setup()
    fireEvent.click(screen.getByRole('radio', { name: 'dataset.importFromQa' }))
    fireEvent.click(screen.getByRole('button', { name: 'cancel' }))
    act(() => ref.current?.open())
    expect(screen.getByRole('radio', { name: 'dataset.localImport' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('textbox')).toHaveValue('')
})
