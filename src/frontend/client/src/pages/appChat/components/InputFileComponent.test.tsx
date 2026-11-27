import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import type { WorkflowFormProps } from '@bisheng/chat';
import { uploadFile, uploadFileWithProgress } from '~/api/apps';
import { uploadArchive } from '~/api/archiveUpload';
import { fileAcceptToInputAccept } from '../fileAcceptUtils';
import { InputForm } from './InputForm';
import InputFileComponent from './InputFileComponent';

const mockShowToast = jest.fn();
const mockShowApiError = jest.fn((error: Error) => mockShowToast({ message: error.message, status: 'warning' }));
jest.mock('~/api/apps', () => ({ uploadFile: jest.fn(), uploadFileWithProgress: jest.fn() }));
jest.mock('~/api/archiveUpload', () => ({ uploadArchive: jest.fn() }));
jest.mock('~/api/request', () => ({ showApiError: (error: Error) => mockShowApiError(error) }));
jest.mock('recoil', () => ({ useRecoilValue: () => ({}), useRecoilState: () => [{}] }));
jest.mock('../store/atoms', () => ({ bishengConfState: {} }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockShowToast }) }));
jest.mock('~/components', () => ({ Button: () => null }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/hooks/useLocalize', () => ({ __esModule: true, default: () => (key: string) => key }));
jest.mock('../useAreaText', () => ({ emitAreaTextEvent: jest.fn(), EVENT_TYPE: {} }));
jest.mock('@bisheng/chat', () => ({
    MessageFrame: ({ children }: { children: React.ReactNode }) => children,
    WorkflowFileField: () => null,
    WorkflowForm: ({ fields, renderField }: WorkflowFormProps) => renderField?.({ id: 'upload', field: fields[0], value: undefined, disabled: false, onChange: () => {}, onFileNameChange: () => {} }),
}));
jest.mock('@bisheng/ui', () => ({ Select: () => null }));
afterEach(() => { cleanup(); jest.clearAllMocks(); });
const extensions = ['.PNG', '.JPEG', '.JPG', '.BMP'];
function pick(container: HTMLElement, files: File[]) {
    const input = container.querySelector('input[type="file"]')!;
    fireEvent.change(input, { target: { files } });
}
it.each([{ fileType: 'image' }, { fileType: ['image'] }])('maps image field config %p to extensions in the real picker', ({ fileType }) => {
    const { container } = render(<InputForm flow={{ name: 'Workflow' }} data={{ node_id: 'node', value: [{ key: 'file', type: 'file', value: 'Image', file_type: fileType }] }} />);
    expect(container.querySelector('input[type="file"]')).toHaveAttribute('accept', [...extensions, '.zip'].join(','));
});
it.each([false, true])('rejects a non-image with multiple=%p and retains the existing value', multiple => {
    const onFileChange = jest.fn();
    const { container } = render(<InputFileComponent isSSO multiple={multiple} suffixes={extensions} value="previous.png" onChange={jest.fn()} onFileChange={onFileChange} />);
    pick(container, [new File(['pdf'], 'document.pdf', { type: 'application/pdf' })]);
    expect(uploadFileWithProgress).not.toHaveBeenCalled();
    expect(onFileChange).not.toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith({ message: 'com_ui_upload_file_type_error', status: 'warning' });
    expect(container).toHaveTextContent('previous.png');
});
it('accepts image extensions regardless of letter case', async () => {
    jest.mocked(uploadFileWithProgress).mockResolvedValue({ file_path: '/photo' });
    const onFileChange = jest.fn();
    const { container } = render(<InputFileComponent isSSO suffixes={extensions} onChange={jest.fn()} onFileChange={onFileChange} />);
    const file = new File(['image'], 'Photo.jPg', { type: 'image/jpeg' });
    pick(container, [file]);
    await waitFor(() => expect(onFileChange).toHaveBeenCalledWith('/photo'));
    expect(uploadFileWithProgress).toHaveBeenCalledWith(file, expect.any(Function));
});
it('uploads only valid images from a mixed multiple selection', async () => {
    jest.mocked(uploadFileWithProgress).mockResolvedValue({ file_path: '/photo' });
    const onFileChange = jest.fn();
    const { container } = render(<InputFileComponent isSSO multiple suffixes={extensions.join(',')} onChange={jest.fn()} onFileChange={onFileChange} />);
    const image = new File(['image'], 'photo.PNG', { type: 'image/png' });
    pick(container, [new File(['text'], 'notes.txt', { type: 'text/plain' }), image]);
    await waitFor(() => expect(onFileChange).toHaveBeenCalledWith(['/photo']));
    expect(uploadFileWithProgress).toHaveBeenCalledTimes(1);
    expect(uploadFileWithProgress).toHaveBeenCalledWith(image, expect.any(Function));
});

it.each([false, true])('shows an upload failure, preserves the value, and permits retry with multiple=%p', async multiple => {
    const failure = new Error('Synthetic upload failed');
    jest.mocked(uploadFileWithProgress).mockRejectedValueOnce(failure).mockResolvedValueOnce({ file_path: '/retry' });
    const onFileChange = jest.fn();
    const { container } = render(<InputFileComponent isSSO multiple={multiple} suffixes={extensions} value="previous.png" onChange={jest.fn()} onFileChange={onFileChange} />);
    pick(container, [new File(['image'], 'photo.PNG', { type: 'image/png' })]);
    await waitFor(() => expect(mockShowApiError).toHaveBeenCalledWith(failure));
    expect(mockShowToast).toHaveBeenCalledWith({ message: failure.message, status: 'warning' });
    expect(onFileChange).not.toHaveBeenCalled();
    expect(container).toHaveTextContent('previous.png');
    pick(container, [new File(['retry'], 'retry.PNG', { type: 'image/png' })]);
    await waitFor(() => expect(onFileChange).toHaveBeenCalledWith(multiple ? ['/retry'] : '/retry'));
});

it.each([false, true])('rejects unsupported workflow document suffixes before any API call and accepts a valid retry with multiple=%p', async multiple => {
    const onFileChange = jest.fn();
    const onChange = jest.fn();
    const onUploadStateChange = jest.fn();
    jest.mocked(uploadFileWithProgress).mockResolvedValueOnce({ file_path: '/retry-text' });
    const { container } = render(<InputFileComponent isSSO multiple={multiple} suffixes={fileAcceptToInputAccept(['file'])}
        value="previous.txt" onChange={onChange} onFileChange={onFileChange} onUploadStateChange={onUploadStateChange} />);
    pick(container, [new File(['unsupported'], 'unsupported.fixture'), ...(multiple ? [new File(['unsupported'], 'another.FIXTURE')] : [])]);
    expect(uploadFileWithProgress).not.toHaveBeenCalled();
    expect(uploadFile).not.toHaveBeenCalled();
    expect(uploadArchive).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
    expect(onFileChange).not.toHaveBeenCalled();
    expect(onUploadStateChange).not.toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith({ message: 'com_ui_upload_file_type_error', status: 'warning' });
    expect(container).toHaveTextContent('previous.txt');
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    expect(input.value).toBe('');
    // Empty text files remain valid; suffix rejection must not invent a size-zero rule.
    const valid = new File([], 'retry.tXt', { type: 'text/plain' });
    pick(container, [valid]);
    await waitFor(() => expect(onFileChange).toHaveBeenCalledWith(multiple ? ['/retry-text'] : '/retry-text'));
    await waitFor(() => expect(onUploadStateChange).toHaveBeenLastCalledWith(false));
});

it.each([false, true])('keeps the previous value after ZIP failure and unlocks retry with multiple=%p', async multiple => {
    const failure = new Error('Synthetic ZIP rejected by archive safety validation');
    const recovered = {
        archive_id: 'synthetic-archive', archive_name: 'retry.ZIP', ignored: [],
        files: [{ file_id: 'synthetic-file', file_name: 'retry.png', file_path: '/safe-retry', relative_path: 'retry.png',
            source_path: '/safe-source', display_name: 'retry.png', archive_id: 'synthetic-archive', size: 5 }],
    };
    jest.mocked(uploadArchive).mockRejectedValueOnce(failure).mockResolvedValueOnce(recovered);
    const onChange = jest.fn();
    const onFileChange = jest.fn();
    const onUploadStateChange = jest.fn();
    const { container } = render(<InputFileComponent isSSO multiple={multiple} suffixes={[...extensions, '.zip']}
        value="previous.png" onChange={onChange} onFileChange={onFileChange} onUploadStateChange={onUploadStateChange} />);
    const zip = new File(['synthetic archive'], 'retry.ZIP', { type: 'application/zip' });
    pick(container, [zip]);
    await waitFor(() => expect(onUploadStateChange).toHaveBeenLastCalledWith(false));
    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ message: failure.message }));
    expect(onFileChange).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
    expect(container).toHaveTextContent('previous.png');
    expect(uploadFileWithProgress).not.toHaveBeenCalled();
    expect(uploadFile).not.toHaveBeenCalled();
    pick(container, [zip]);
    await waitFor(() => expect(onFileChange).toHaveBeenCalledWith(['/safe-retry']));
    await waitFor(() => expect(onUploadStateChange).toHaveBeenLastCalledWith(false));
    expect(uploadArchive).toHaveBeenCalledTimes(2);
    expect(uploadArchive).toHaveBeenLastCalledWith(zip, [...extensions, '.zip'].join(','));
});
