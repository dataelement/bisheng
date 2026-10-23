import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import PreviewResult from './PreviewResult'
import { previewFileSplitApi } from '@/controllers/API'
import { normalizeApiError } from '@bisheng/api-client'
import { notification } from '@bisheng/ui'

vi.mock('@/controllers/API', () => ({ previewFileSplitApi: vi.fn(() => vi.fn()), delChunkInPreviewApi: vi.fn(), updatePreviewChunkApi: vi.fn() }))
vi.mock('@/controllers/request', async (importOriginal) => ({ ...await importOriginal<typeof import('@/controllers/request')>() }))
vi.mock('./PreviewFile', () => ({ default: ({ previewErrorMessage }: { previewErrorMessage: string }) => <span>{previewErrorMessage}</span> }))
vi.mock('./PreviewParagraph', () => ({ default: () => null }))
vi.mock('./RichPreviewFile', () => ({ buildMediaUploadPreviewData: vi.fn(), isMediaUploadSuffix: () => false }))
afterEach(cleanup)
it('synchronizes strategy type when switching between document and table previews', async () => {
    const onFileTypeChange = vi.fn()
    const rules = { fileList: [
        { id: 'document', fileName: 'doc.pdf', fileType: 'file', suffix: 'pdf', filePath: '/doc.pdf' },
        { id: 'spreadsheet', fileName: 'sheet.xlsx', fileType: 'table', suffix: 'xlsx', filePath: '/sheet.xlsx' },
    ] }
    render(<MemoryRouter><PreviewResult step={3} rules={rules} previewCount={1} applyEachCell={false}
        cellGeneralConfig={{}} handlePreviewResult={() => undefined} onFileTypeChange={onFileTypeChange} /></MemoryRouter>)
    await waitFor(() => expect(onFileTypeChange).toHaveBeenLastCalledWith('file'))
    fireEvent.click(screen.getByRole('combobox'))
    fireEvent.click(await screen.findByRole('option', { name: /sheet\.xlsx/ }))
    await waitFor(() => expect(onFileTypeChange).toHaveBeenLastCalledWith('table'))
    fireEvent.click(screen.getByRole('combobox'))
    fireEvent.click(await screen.findByRole('option', { name: /doc\.pdf/ }))
    await waitFor(() => expect(onFileTypeChange).toHaveBeenLastCalledWith('file'))
})

it('renders the specialized preview error from the original ApiError without opening a duplicate notice', async () => {
    const error = normalizeApiError(new Error('ASR request failed'), { message: 'ASR request failed',
        envelope: { status_code: 10954, data: { exception: 'ASR request failed' } },
    })
    error.presentation = 'toast'
    vi.mocked(previewFileSplitApi).mockImplementationOnce((_data, onEvent) => {
        queueMicrotask(() => onEvent('error', error))
        return vi.fn()
    })
    const notice = vi.spyOn(notification, 'open')
    const onPreviewResult = vi.fn()
    render(<MemoryRouter><PreviewResult step={3} rules={{ fileList: [
        { id: 'document', fileName: 'doc.pdf', fileType: 'file', suffix: 'pdf', filePath: '/doc.pdf' },
    ] }} previewCount={1} applyEachCell={false} cellGeneralConfig={{}}
        handlePreviewResult={onPreviewResult} onFileTypeChange={vi.fn()} /></MemoryRouter>)
    await screen.findByText('mediaAsrRequestFailed')
    expect(onPreviewResult).toHaveBeenCalledWith(false)
    expect(notice).not.toHaveBeenCalled()
})
