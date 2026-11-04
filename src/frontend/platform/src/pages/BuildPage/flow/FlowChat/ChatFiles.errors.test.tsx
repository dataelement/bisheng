import { normalizeApiError } from '@bisheng/api-client';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ChatFiles, { type ChatFilesHandle } from './ChatFiles';

const mock = vi.hoisted(() => ({ upload: vi.fn(), report: vi.fn(), notice: vi.fn() }));
vi.mock('@/controllers/API/flow', () => ({ uploadChatFile: mock.upload }));
vi.mock('@/controllers/request', () => ({ showApiError: mock.report }));
vi.mock('@bisheng/ui', () => ({ notification: { open: mock.notice } }));
vi.mock('@/contexts/locationContext', async () => ({ locationContext: (await import('react')).createContext({ appConfig: { uploadFileMaxSize: 50 } }) }));
beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

it.each(['toast', 'global', 'canceled'])('removes failed attachments and releases the upload counter for %s errors without another notice', async (kind) => {
    const error = normalizeApiError(kind === 'canceled' ? { code: 'ERR_CANCELED' } : {}, { message: 'Upload failed' });
    if (kind === 'toast' || kind === 'global') error.presentation = kind;
    mock.upload.mockRejectedValueOnce(error).mockResolvedValueOnce({ file_path: '/ok.txt' });
    const ref = createRef<ChatFilesHandle>();
    const onChange = vi.fn();
    render(<ChatFiles ref={ref} v="v1" onChange={onChange} />);
    act(() => ref.current!.upload([new File(['x'], 'failed.txt')]));
    await waitFor(() => expect(mock.report).toHaveBeenCalledWith(error));
    expect(screen.queryByText('failed.txt')).not.toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith([]);
    expect(mock.notice).not.toHaveBeenCalled();
    act(() => ref.current!.upload([new File(['ok'], 'ok.txt')]));
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith([{ path: '/ok.txt', name: 'ok.txt' }]));
});

it('keeps the attachment batch pending after one failure until the remaining upload completes', async () => {
    let finish: (result: { file_path: string }) => void = () => undefined;
    mock.upload.mockRejectedValueOnce(new Error('First upload failed')).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const ref = createRef<ChatFilesHandle>();
    const onChange = vi.fn();
    render(<ChatFiles ref={ref} v="v1" onChange={onChange} />);
    act(() => ref.current!.upload([new File(['a'], 'failed.txt'), new File(['b'], 'pending.txt')]));
    await waitFor(() => expect(mock.report).toHaveBeenCalled());
    expect(onChange).toHaveBeenLastCalledWith(null);
    expect(onChange.mock.calls.some(([files]) => Array.isArray(files) && files.some(file => !file.path))).toBe(false);
    await act(async () => { finish({ file_path: '/pending.txt' }); });
    expect(onChange).toHaveBeenLastCalledWith([{ path: '/pending.txt', name: 'pending.txt' }]);
});
