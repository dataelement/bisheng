import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IconUploadSection } from './IconUploadSection';

const mocks = vi.hoisted(() => ({ upload: vi.fn(), toast: vi.fn(), compressError: null as Error | null }));
vi.mock('@/controllers/API', () => ({ uploadLibFile: mocks.upload }));
vi.mock('@/components/bs-ui/toast/use-toast', () => ({
    toast: mocks.toast,
    useToast: () => ({ toast: mocks.toast, message: mocks.toast }),
}));
vi.mock('compressorjs', () => ({
    default: class {
        constructor(file: File, options: { success: (result: Blob) => void; error: (error: Error) => void }) {
            queueMicrotask(() => mocks.compressError ? options.error(mocks.compressError) : options.success(file));
        }
    },
}));

const file = new File(['image'], 'logo.png', { type: 'image/png' });
const uploaded = { file_path: '/bisheng/icon/new.png', relative_path: 'icon/new.png' };
function mount(label = 'Assistant logo', image = '/old.png') {
    const onUpload = vi.fn();
    const view = render(<IconUploadSection label={label} image={image} enabled onToggle={vi.fn()} onUpload={onUpload} />);
    return { ...view, onUpload, input: view.container.querySelector('input')! };
}

beforeEach(() => { vi.clearAllMocks(); mocks.compressError = null; });
afterEach(cleanup);

describe('workbench logo upload', () => {
    it.each(['Sidebar logo', 'Assistant logo'])('uploads %s and passes the stored image to its own field', async label => {
        mocks.upload.mockResolvedValue(uploaded);
        const { input, onUpload } = mount(label);
        await userEvent.upload(input, file);
        await waitFor(() => expect(onUpload).toHaveBeenCalledWith(uploaded.file_path, uploaded.relative_path));
        const [data, , type] = mocks.upload.mock.calls[0];
        expect(data.get('file').name).toBe('logo.png');
        expect(type).toBe('icon');
    });

    it('keeps the original logo and shows the server error, then retries the same file', async () => {
        mocks.upload.mockRejectedValueOnce('Storage unavailable').mockResolvedValueOnce(uploaded);
        const { input, onUpload } = mount();
        await userEvent.upload(input, file);
        await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ description: 'Storage unavailable', variant: 'error' })));
        expect(onUpload).toHaveBeenCalledTimes(0);
        expect(screen.getByRole('img')).toHaveAttribute('src', '/old.png');
        await userEvent.upload(input, file);
        await waitFor(() => expect(onUpload).toHaveBeenCalledWith(uploaded.file_path, uploaded.relative_path));
        expect(mocks.upload).toHaveBeenCalledTimes(2);
    });

    it('restores the picker after an image decoding failure and accepts the same file again', async () => {
        mocks.compressError = new Error('Invalid image');
        const { input, onUpload } = mount();
        await userEvent.upload(input, file);
        await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ description: 'Invalid image' })));
        expect(onUpload).toHaveBeenCalledTimes(0);
        expect(mocks.upload).toHaveBeenCalledTimes(0);
        mocks.compressError = null;
        mocks.upload.mockResolvedValue(uploaded);
        await userEvent.upload(input, file);
        await waitFor(() => expect(onUpload).toHaveBeenCalledWith(uploaded.file_path, uploaded.relative_path));
    });

    it('keeps the current icon while a request is in flight and restores the picker afterward', async () => {
        let resolve!: (result: typeof uploaded) => void;
        mocks.upload.mockReturnValue(new Promise(r => { resolve = r; }));
        const { input, onUpload } = mount();
        await userEvent.upload(input, file);
        expect(input).toBeDisabled();
        expect(screen.getByRole('img')).toHaveAttribute('src', '/old.png');
        await act(async () => resolve(uploaded));
        await waitFor(() => expect(input).toBeEnabled());
        expect(onUpload).toHaveBeenCalledTimes(1);
    });

    it('preserves an absolute uploaded image URL', () => {
        mount('Assistant logo', 'https://assets.example/logo.png');
        expect(screen.getByRole('img')).toHaveAttribute('src', 'https://assets.example/logo.png');
    });
});
