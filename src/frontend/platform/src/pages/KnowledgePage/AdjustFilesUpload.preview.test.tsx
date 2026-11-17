import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import AdjustFilesUpload from './AdjustFilesUpload';
import { rebUploadFile } from '@/controllers/API';

const captured = vi.hoisted(() => vi.fn());
vi.mock('@/controllers/API', () => ({ rebUploadFile: vi.fn().mockResolvedValue({ id: 42 }), retryKnowledgeFileApi: vi.fn() }));
vi.mock('@/controllers/API/permission', () => ({ checkResourceActionApi: vi.fn().mockResolvedValue({ allowed: true }) }));
vi.mock('./components/FileUploadStep2', () => ({ default: (props: { resultFiles: unknown[]; onNext: (step: number, config: unknown) => void }) => {
    captured(props.resultFiles);
    return <button onClick={() => props.onNext(2, { rules: { fileList: [{ id: 42, filePath: 'knowledge-preview-file:42:original', originalUrl: '/original.pdf', previewFileId: 42 }], separator: [] }, cellGeneralConfig: {} })}>continue</button>;
} }));
vi.mock('./components/PreviewResult', () => ({ default: () => null }));
vi.mock('./components/FileUploadStep4', () => ({ default: () => null }));
vi.mock('./components/DuplicateFileDialog', () => ({ DialogWithRepeatFiles: () => null }));

it('carries the existing file ID to preview while retaining the path for reprocessing', async () => {
    render(<MemoryRouter initialEntries={[{ pathname: '/filelib/adjust/7', state: { fileData: { id: '42', name: 'doc.pdf', filePath: '/original.pdf' } } }]}>
        <Routes><Route path="/filelib/adjust/:fileId" element={<AdjustFilesUpload />} /></Routes>
    </MemoryRouter>);
    await waitFor(() => expect(captured).toHaveBeenCalled());
    expect(captured.mock.lastCall?.[0][0]).toMatchObject({ id: '42', file_path: 'knowledge-preview-file:42:original', originalUrl: '/original.pdf', preview_file_id: 42 });
    fireEvent.click(screen.getByText('continue'));
    fireEvent.click(screen.getByText('nextStep'));
    await waitFor(() => expect(rebUploadFile).toHaveBeenCalledWith(expect.objectContaining({ kb_file_id: 42, file_path: 'knowledge-preview-file:42:original' })));
});
