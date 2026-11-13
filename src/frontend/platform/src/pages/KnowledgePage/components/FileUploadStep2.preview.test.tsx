import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import FileUploadStep2 from './FileUploadStep2';

const capture = vi.fn();
vi.mock('./PreviewResult', () => ({ default: (props: unknown) => { capture(props); return null; } }));
vi.mock('./RuleFile', () => ({ default: () => null }));
vi.mock('./RuleTable', () => ({ default: () => null }));

it.each([
    { id: 'local', preview_upload_ref: 'signed-ref', expected: { previewUploadRef: 'signed-ref' } },
    { id: 42, preview_file_id: 42, originalUrl: '/view.pdf', expected: { previewFileId: 42, originalUrl: '/view.pdf' } },
])('carries the preview source through rule configuration for $id', async ({ expected, ...file }) => {
    capture.mockClear();
    render(<MemoryRouter><FileUploadStep2 step={2} isSubmitting={false} onNext={vi.fn()} onPrev={vi.fn()}
        resultFiles={[{ ...file, fileName: 'doc.pdf', file_path: '/original.pdf', fileType: 'file', suffix: 'pdf', split_rule: null }]} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'previewResults' }));
    await waitFor(() => expect(capture).toHaveBeenCalled());
    expect(capture.mock.lastCall?.[0].rules.fileList[0]).toMatchObject({ filePath: '/original.pdf', ...expected });
});
