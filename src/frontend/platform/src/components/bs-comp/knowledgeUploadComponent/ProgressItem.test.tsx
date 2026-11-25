import { render, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { uploadFileApi } from '@/controllers/API';
import ProgressItem from './ProgressItem';
import { ProgressStatus } from '.';

vi.mock('@/controllers/API', () => ({ uploadFileApi: vi.fn() }));

it('retains the upload reference alongside the processing path', async () => {
    vi.mocked(uploadFileApi).mockImplementation(async ({ onFinish }) => {
        onFinish?.({ file_path: '/tmp/file.pdf', preview_upload_ref: 'signed-ref' });
    });
    const onResulte = vi.fn();
    render(<ProgressItem analysis={false} knowledgeId="1" onResulte={onResulte} item={{
        id: 'local', file: new File(['x'], 'file.pdf'), fileName: 'file.pdf',
        progress: ProgressStatus.Uploading, error: false,
    }} />);
    await waitFor(() => expect(onResulte).toHaveBeenCalledWith('local', expect.objectContaining({
        file_path: '/tmp/file.pdf', preview_upload_ref: 'signed-ref',
    })));
});
