import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import PreviewResult from './PreviewResult'

vi.mock('@/controllers/API', () => ({ previewFileSplitApi: vi.fn(() => vi.fn()), delChunkInPreviewApi: vi.fn(), updatePreviewChunkApi: vi.fn() }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: vi.fn() }))
vi.mock('./PreviewFile', () => ({ default: () => null }))
vi.mock('./PreviewParagraph', () => ({ default: () => null }))
vi.mock('./RichPreviewFile', () => ({ buildMediaUploadPreviewData: vi.fn(), isMediaUploadSuffix: () => false }))
vi.mock('@/components/bs-ui/select', () => ({
    Select: ({ children, value, onValueChange }: { children: ReactNode; value: string; onValueChange: (value: string) => void }) =>
        <select aria-label="preview-file" value={value} onChange={event => onValueChange(event.target.value)}>{children}</select>,
    SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
    SelectItem: ({ value }: { value: string }) => <option value={value}>{value}</option>,
    SelectTrigger: () => null,
    SelectValue: () => null,
}))
afterEach(cleanup)
it('synchronizes strategy type when switching between document and table previews', async () => {
    const onFileTypeChange = vi.fn()
    const rules = { fileList: [
        { id: 'document', fileType: 'file', suffix: 'pdf', filePath: '/doc.pdf' },
        { id: 'spreadsheet', fileType: 'table', suffix: 'xlsx', filePath: '/sheet.xlsx' },
    ] }
    render(<MemoryRouter><PreviewResult step={3} rules={rules} previewCount={1} applyEachCell={false}
        cellGeneralConfig={{}} handlePreviewResult={() => undefined} onFileTypeChange={onFileTypeChange} /></MemoryRouter>)
    await waitFor(() => expect(onFileTypeChange).toHaveBeenLastCalledWith('file'))
    fireEvent.change(screen.getByLabelText('preview-file'), { target: { value: 'spreadsheet' } })
    await waitFor(() => expect(onFileTypeChange).toHaveBeenLastCalledWith('table'))
    fireEvent.change(screen.getByLabelText('preview-file'), { target: { value: 'document' } })
    await waitFor(() => expect(onFileTypeChange).toHaveBeenLastCalledWith('file'))
})
