import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi, type MockInstance } from 'vitest';
import { uploadArchive } from '@/controllers/API/archiveUpload';
import { uploadFile } from '@/controllers/API';
import { uploadFileWithProgress } from '@/modals/UploadModal/upload';
import { showApiError } from '@/controllers/request';
import InputFileComponent from './index';

vi.mock('@/controllers/API/archiveUpload', () => ({ uploadArchive: vi.fn() }));
vi.mock('@/controllers/API', () => ({ uploadFile: vi.fn() }));
vi.mock('@/modals/UploadModal/upload', () => ({ uploadFileWithProgress: vi.fn() }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('@/contexts/locationContext', async () => ({ locationContext: (await import('react')).createContext({ appConfig: {} }) }));
vi.mock('@/contexts/tabsContext', async () => ({ TabsContext: (await import('react')).createContext({ flow: { id: 'synthetic-flow' } }) }));
vi.mock('@/contexts/alertContext', async () => ({ alertContext: (await import('react')).createContext({ setErrorData: vi.fn() }) }));
vi.mock('@bisheng/ui', () => ({ Button: () => null, notification: { open: vi.fn() } }));
vi.mock('../bs-icons/loading', () => ({ LoadIcon: () => null }));

let inputClick: MockInstance<() => void>;
beforeEach(() => {
    inputClick = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks(); });

function selectFiles(files: File[]) {
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    const pickedInput = inputClick.mock.contexts.at(-1) as HTMLInputElement | undefined;
    expect(pickedInput).toBeDefined();
    fireEvent.change(pickedInput!, { target: { files } });
}

function setup(multiple: boolean, isSSO = true) {
    const onChange = vi.fn();
    const onFileChange = vi.fn();
    const onUploadStateChange = vi.fn();
    render(<InputFileComponent disabled={false} multiple={multiple} isSSO={isSSO} suffixes=".TXT,.zip" value="previous.txt"
        onChange={onChange} onFileChange={onFileChange} onUploadStateChange={onUploadStateChange}
        renderControl={({ value, loading, onClick }) => <button type="button" aria-label="Upload" disabled={loading} onClick={onClick}>{value}</button>} />);
    return { onChange, onFileChange, onUploadStateChange };
}

it.each([false, true])('preserves the platform form value on ZIP failure and permits retry with multiple=%p', async multiple => {
    const failure = new Error('Synthetic broken ZIP');
    const child = { file_id: 'synthetic-file', file_name: 'safe.txt', file_path: '/safe-text', relative_path: 'safe.txt', source_path: '/safe-source', display_name: 'safe.txt', archive_id: 'synthetic-archive', size: 4 };
    vi.mocked(uploadArchive).mockRejectedValueOnce(failure).mockResolvedValueOnce([child]);
    const { onChange, onFileChange, onUploadStateChange } = setup(multiple);
    const zip = new File(['synthetic broken archive'], 'broken-archive.zip', { type: 'application/zip' });
    selectFiles([zip]);
    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(failure));
    await waitFor(() => expect(onUploadStateChange).toHaveBeenLastCalledWith(false));
    expect(onChange).not.toHaveBeenCalled();
    expect(onFileChange).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Upload' })).toHaveTextContent('previous.txt');
    expect(uploadFileWithProgress).not.toHaveBeenCalled();
    expect(uploadFile).not.toHaveBeenCalled();
    selectFiles([zip]);
    await waitFor(() => expect(onFileChange).toHaveBeenCalledWith(['/safe-text']));
    await waitFor(() => expect(onUploadStateChange).toHaveBeenLastCalledWith(false));
    expect(uploadArchive).toHaveBeenCalledTimes(2);
    expect(uploadArchive).toHaveBeenLastCalledWith(zip, '.TXT,.zip');
});

it.each([[false, false], [true, false], [false, true], [true, true]])('preserves ordinary-file failure feedback and retry with multiple=%p isSSO=%p', async (multiple, isSSO) => {
    const failure = new Error('Synthetic platform file upload failed');
    const upload = isSSO ? vi.mocked(uploadFileWithProgress) : vi.mocked(uploadFile);
    upload.mockRejectedValueOnce(failure).mockResolvedValueOnce({ file_path: '/retry-text' });
    const { onChange, onFileChange, onUploadStateChange } = setup(multiple, isSSO);
    const text = new File([], 'retry.TXT', { type: 'text/plain' });
    selectFiles([text]);
    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(failure));
    await waitFor(() => expect(onUploadStateChange).toHaveBeenLastCalledWith(false));
    expect(onChange).not.toHaveBeenCalled();
    expect(onFileChange).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Upload' })).toHaveTextContent('previous.txt');
    selectFiles([text]);
    await waitFor(() => expect(onFileChange).toHaveBeenCalledWith(multiple ? ['/retry-text'] : '/retry-text'));
    await waitFor(() => expect(onUploadStateChange).toHaveBeenLastCalledWith(false));
    expect(uploadArchive).not.toHaveBeenCalled();
});
