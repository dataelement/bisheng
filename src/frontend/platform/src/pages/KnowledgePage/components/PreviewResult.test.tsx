import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import PreviewResult from './PreviewResult'
import { delChunkInPreviewApi, previewFileSplitApi, updatePreviewChunkApi } from '@/controllers/API'
import { normalizeApiError } from '@bisheng/api-client'
import { notification } from '@bisheng/ui'

vi.mock('@/controllers/API', () => ({ previewFileSplitApi: vi.fn(() => vi.fn()), delChunkInPreviewApi: vi.fn(), updatePreviewChunkApi: vi.fn() }))
vi.mock('@/controllers/request', async (importOriginal) => ({ ...await importOriginal<typeof import('@/controllers/request')>() }))
vi.mock('./PreviewFile', () => ({ default: ({ previewErrorMessage, urlState }: { previewErrorMessage: string; urlState: { url: string } }) => <><span>{previewErrorMessage}</span><span data-testid="viewer-url">{urlState.url}</span></> }))
vi.mock('./PreviewParagraph', () => ({ default: ({ onDel, onChange }: { onDel: (index: number, text: string) => void; onChange: (index: number, text: string) => void }) => <><button onClick={() => onDel(0, 'old')}>delete chunk</button><button onClick={() => onChange(0, 'new')}>edit chunk</button></> }))
vi.mock('./RichPreviewFile', () => ({ buildMediaUploadPreviewData: vi.fn(), isMediaUploadSuffix: () => false }))
afterEach(cleanup)
it.each([
    { id: 'local', filePath: '/upload.pdf', previewUploadRef: 'signed-ref', expected: { file_path: '/upload.pdf', preview_upload_ref: 'signed-ref' } },
    { id: 42, filePath: 'knowledge-preview-file:42:original', originalUrl: '/existing.pdf', previewUrl: '/converted.pdf', previewFileId: 42, expected: { file_path: 'knowledge-preview-file:42:converted', preview_file_id: 42, preview_source: 'converted' } },
])('sends the secure preview source for $id', async ({ expected, ...file }) => {
    vi.mocked(previewFileSplitApi).mockClear()
    render(<MemoryRouter><PreviewResult step={3} showPreview rules={{ fileList: [{ ...file, fileName: 'doc.pdf', fileType: 'file', suffix: 'pdf' }] }}
        previewCount={1} applyEachCell={false} cellGeneralConfig={{}} handlePreviewResult={() => undefined} /></MemoryRouter>)
    await waitFor(() => expect(previewFileSplitApi).toHaveBeenCalled())
    expect(vi.mocked(previewFileSplitApi).mock.calls[0][0].file_list[0]).toMatchObject(expected)
})

it.each([
    { id: 'local', filePath: '/original.pdf', previewUploadRef: 'signed-ref' },
    { id: 42, filePath: 'knowledge-preview-file:42:original', originalUrl: '/original.pdf', previewFileId: 42 },
])('uses the matching cache identity for chunk edits and deletion: $id', async (file) => {
    vi.mocked(delChunkInPreviewApi).mockResolvedValueOnce({} as Awaited<ReturnType<typeof delChunkInPreviewApi>>)
    render(<MemoryRouter><PreviewResult step={3} kId={7} rules={{ fileList: [{ ...file, fileName: 'doc.pdf', fileType: 'file', suffix: 'pdf' }] }}
        previewCount={1} applyEachCell={false} cellGeneralConfig={{}} handlePreviewResult={() => undefined} /></MemoryRouter>)
    await waitFor(() => expect(previewFileSplitApi).toHaveBeenCalled())
    fireEvent.click(screen.getByText('edit chunk'))
    fireEvent.click(screen.getByText('delete chunk'))
    expect(updatePreviewChunkApi).toHaveBeenCalledWith(expect.objectContaining({ file_path: file.filePath }))
    await waitFor(() => expect(delChunkInPreviewApi).toHaveBeenCalledWith(expect.objectContaining({ file_path: file.filePath })))
})

it.each([
    { showPreview: false, previewUrl: '/converted.pdf' },
    { showPreview: true, previewUrl: '' },
])('uses the original source when converted preview is not selected', async ({ showPreview, previewUrl }) => {
    vi.mocked(previewFileSplitApi).mockClear()
    render(<MemoryRouter><PreviewResult step={3} showPreview={showPreview} rules={{ fileList: [{ id: '42', fileName: 'doc.pdf', fileType: 'file', suffix: 'pdf', filePath: 'knowledge-preview-file:42:original', previewFileId: 42, previewUrl }] }}
        previewCount={1} applyEachCell={false} cellGeneralConfig={{}} handlePreviewResult={() => undefined} /></MemoryRouter>)
    await waitFor(() => expect(previewFileSplitApi).toHaveBeenCalled())
    expect(vi.mocked(previewFileSplitApi).mock.calls[0][0].file_list[0]).toMatchObject({ file_path: 'knowledge-preview-file:42:original', preview_file_id: 42, preview_source: 'original' })
})

it('uses converted cache identity for converted preview chunk mutations', async () => {
    vi.mocked(delChunkInPreviewApi).mockResolvedValueOnce({} as Awaited<ReturnType<typeof delChunkInPreviewApi>>)
    render(<MemoryRouter><PreviewResult step={2} showPreview kId={7} rules={{ fileList: [{ id: '42', fileName: 'doc.pdf', fileType: 'file', suffix: 'pdf', filePath: 'knowledge-preview-file:42:original', previewUrl: '/converted.pdf', previewFileId: 42 }] }}
        previewCount={1} applyEachCell={false} cellGeneralConfig={{}} handlePreviewResult={() => undefined} /></MemoryRouter>)
    await waitFor(() => expect(previewFileSplitApi).toHaveBeenCalled())
    fireEvent.click(screen.getByText('edit chunk'))
    fireEvent.click(screen.getByText('delete chunk'))
    expect(updatePreviewChunkApi).toHaveBeenCalledWith(expect.objectContaining({ file_path: 'knowledge-preview-file:42:converted' }))
    await waitFor(() => expect(delChunkInPreviewApi).toHaveBeenCalledWith(expect.objectContaining({ file_path: 'knowledge-preview-file:42:converted' })))
})

it('uses the original URL for the existing-file viewer after a preview error', async () => {
    vi.mocked(previewFileSplitApi).mockImplementationOnce((_data, onEvent) => {
        queueMicrotask(() => onEvent('error', { message: 'failed' }))
        return vi.fn()
    })
    render(<MemoryRouter><PreviewResult step={3} rules={{ fileList: [{ id: '42', fileName: 'doc.pdf', fileType: 'file', suffix: 'pdf', filePath: 'knowledge-preview-file:42:original', originalUrl: '/original.pdf', previewFileId: 42 }] }}
        previewCount={1} applyEachCell={false} cellGeneralConfig={{}} handlePreviewResult={() => undefined} /></MemoryRouter>)
    await waitFor(() => expect(screen.getByTestId('viewer-url')).toHaveTextContent('/original.pdf'))
})

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
