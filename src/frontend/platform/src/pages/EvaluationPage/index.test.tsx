import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import EvaluationPage from './index'

const mock = vi.hoisted(() => ({ reload: vi.fn(), download: vi.fn(), remove: vi.fn().mockResolvedValue({}), url: vi.fn().mockResolvedValue({ url: 'result.csv' }) }))
vi.mock('@/components/bs-comp/FileView', () => ({ checkSassUrl: (url: string) => url }))
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: ({ onOk }: { onOk: (next: () => void) => void }) => onOk(vi.fn()) }))
vi.mock('@/controllers/request', async (importOriginal) => ({ ...await importOriginal<typeof import('@/controllers/request')>() }))
vi.mock('@/controllers/API/evaluate', () => ({ getEvaluationApi: vi.fn(), getEvaluationUrlApi: mock.url, deleteEvaluationApi: mock.remove }))
vi.mock('@/util/utils', () => ({ downloadFile: mock.download }))
vi.mock('@/util/hook', () => ({ useTable: () => ({ page: 1, pageSize: 20, total: 3, loading: false, setPage: vi.fn(), reload: mock.reload, data: [
    { id: 1, file_name: 'running.csv', unique_name: 'App', exec_type: 'assistant', status: 1, progress: '50%', create_time: '2026-10-20T10:00:00' },
    { id: 2, file_name: 'failed.csv', unique_name: 'App', exec_type: 'workflow', status: 2, description: 'Model unavailable', create_time: '2026-10-20T10:00:00' },
    { id: 3, file_name: 'done.csv', unique_name: 'App', exec_type: 'assistant', status: 3, result_file_path: 'results/done', result_score: { answer_f1: '0.9' }, create_time: '2026-10-20T10:00:00' },
] }) }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('keeps progress, scores, failure details and download availability', async () => {
    render(<MemoryRouter><EvaluationPage /></MemoryRouter>)
    expect(screen.getByText('inProgress', { exact: false })).toHaveTextContent('50%')
    const failed = screen.getByText('failed.csv').closest('tr')!
    expect(within(failed).queryByRole('button', { name: 'evaluation.download' })).not.toBeInTheDocument()
    expect(within(failed).getByLabelText('Model unavailable')).toBeInTheDocument()
    const done = screen.getByText('done.csv').closest('tr')!
    expect(within(done).getByText('F1', { exact: false })).toHaveTextContent('0.9')
    fireEvent.click(within(done).getByRole('button', { name: 'evaluation.download' }))
    await waitFor(() => expect(mock.download).toHaveBeenCalledWith('result.csv', 'done.csv'))
})
it('still confirms deletion and refreshes the list', async () => {
    render(<MemoryRouter><EvaluationPage /></MemoryRouter>)
    fireEvent.click(within(screen.getByText('done.csv').closest('tr')!).getByRole('button', { name: 'delete' }))
    await waitFor(() => expect(mock.remove).toHaveBeenCalledWith(3))
    await waitFor(() => expect(mock.reload).toHaveBeenCalledTimes(1))
})
