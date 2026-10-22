import { normalizeApiError } from '@bisheng/api-client';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import SimpleUpload from './simple';

const mock = vi.hoisted(() => ({
    post: vi.fn(), report: vi.fn(), notice: vi.fn(),
    drop: undefined as undefined | ((files: File[]) => Promise<void>),
}));
vi.mock('@/controllers/request', () => ({ default: { post: mock.post }, showApiError: mock.report }));
vi.mock('@bisheng/ui', () => ({ notification: { open: mock.notice } }));
vi.mock('react-dropzone', () => ({ useDropzone: ({ onDrop }: { onDrop: (files: File[]) => Promise<void> }) => {
    mock.drop = onDrop;
    return { getRootProps: () => ({}), getInputProps: () => ({}), isDragActive: false };
} }));
beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

it('terminates a rejected upload without invoking success or repeating the request notice', async () => {
    const error = normalizeApiError(new Error('Upload failed'), { message: 'Upload failed' });
    error.presentation = 'toast';
    mock.post.mockRejectedValueOnce(error);
    const onSuccess = vi.fn();
    render(<SimpleUpload filekey="file" uploadUrl="/upload" accept={['json']} onSuccess={onSuccess} />);
    await act(() => mock.drop!([new File(['{}'], 'data.json')]));
    expect(mock.report).toHaveBeenCalledWith(error);
    expect(mock.notice).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
});

it.each([true, false])('keeps API and local pre-check failures distinct (API=%s)', async (api) => {
    const error = api ? normalizeApiError({ code: 'ERR_CANCELED' }, { message: 'Canceled' }) : new Error('Invalid spreadsheet');
    render(<SimpleUpload filekey="file" uploadUrl="/upload" accept={['xlsx']} onSuccess={vi.fn()} preCheck={vi.fn().mockRejectedValueOnce(error)} />);
    await act(() => mock.drop!([new File(['x'], 'data.xlsx')]));
    if (api) {
        expect(mock.report).toHaveBeenCalledWith(error);
        expect(mock.notice).not.toHaveBeenCalled();
    } else expect(mock.notice).toHaveBeenCalledWith(expect.objectContaining({ description: 'Invalid spreadsheet' }));
    expect(mock.post).not.toHaveBeenCalled();
});
