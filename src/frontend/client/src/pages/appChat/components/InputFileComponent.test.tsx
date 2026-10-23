import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import type { WorkflowFormProps } from '@bisheng/chat';
import { uploadFileWithProgress } from '~/api/apps';
import { InputForm } from './InputForm';
import InputFileComponent from './InputFileComponent';

const mockShowToast = jest.fn();
jest.mock('~/api/apps', () => ({ uploadFile: jest.fn(), uploadFileWithProgress: jest.fn() }));
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
    expect(container.querySelector('input[type="file"]')).toHaveAttribute('accept', extensions.join(','));
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
