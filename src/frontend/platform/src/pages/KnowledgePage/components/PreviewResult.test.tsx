import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import PreviewResult from './PreviewResult'

vi.mock('@/controllers/API', () => ({ previewFileSplitApi: vi.fn(() => vi.fn()), delChunkInPreviewApi: vi.fn(), updatePreviewChunkApi: vi.fn() }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: vi.fn() }))
vi.mock('./PreviewFile', () => ({ default: () => null }))
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
