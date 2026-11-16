import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Word from './Word';

const mocks = vi.hoisted(() => ({ sign: vi.fn(), editor: vi.fn(), report: vi.fn(), notice: vi.fn(), destroy: vi.fn() }));
vi.mock('@/controllers/API/flow', () => ({ getOfficeTokenApi: mocks.sign }));
vi.mock('@/controllers/request', () => ({ showApiError: mocks.report }));
vi.mock('@bisheng/ui', () => ({ notification: { open: mocks.notice } }));
vi.mock('../../../contexts/locationContext', async () => {
    const { createContext } = await import('react');
    return { locationContext: createContext({ appConfig: { officeUrl: 'https://office.test' } }) };
});

beforeEach(() => {
    vi.clearAllMocks();
    mocks.editor.mockImplementation(() => ({ destroyEditor: mocks.destroy }));
    Object.assign(window, { DocsAPI: { DocEditor: mocks.editor }, editor: undefined });
});
afterEach(cleanup);

it.each([false, true])('does not open an unsigned editor after issuer rejection (workflow=%s)', async workflow => {
    const error = new Error('synthetic authorization rejection');
    mocks.sign.mockRejectedValue(error);
    render(<Word data={{ key: 'server-key', path: 'https://minio.test/bucket/report/a.docx' }} workflow={workflow} />);
    await waitFor(() => expect(mocks.sign).toHaveBeenCalledTimes(1));
    await act(async () => { await Promise.resolve(); });
    expect(mocks.editor).not.toHaveBeenCalled();
    expect(mocks.report).toHaveBeenCalledWith(error);
});

it.each([{}, { token: '' }, { token: '  ' }])('does not boot with missing token %j', async response => {
    mocks.sign.mockResolvedValue(response);
    render(<Word data={{ key: 'server-key', path: 'https://minio.test/bucket/report/a.docx' }} />);
    await waitFor(() => expect(mocks.sign).toHaveBeenCalledTimes(1));
    await act(async () => { await Promise.resolve(); });
    expect(mocks.editor).not.toHaveBeenCalled();
    expect(mocks.report).toHaveBeenCalledTimes(1);
});

it.each([undefined, null, {}, 'invalid'])('refuses a token without canonical config %j', async config => {
    mocks.sign.mockResolvedValue({ token: 'synthetic-issued-token', config });
    render(<Word data={{ key: 'server-key', path: 'https://minio.test/bucket/report/a.docx' }} />);
    await waitFor(() => expect(mocks.sign).toHaveBeenCalledTimes(1));
    await act(async () => { await Promise.resolve(); });
    expect(mocks.editor).not.toHaveBeenCalled();
    expect(mocks.report).toHaveBeenCalledTimes(1);
});

it.each([false, true])('sends explicit builtin source metadata without trusting an asset URL (workflow=%s)', async workflow => {
    mocks.sign.mockRejectedValue(new Error('synthetic stop'));
    render(<Word data={{ key: 'server-key', path: '', source_kind: 'empty' }} workflow={workflow} />);
    await waitFor(() => expect(mocks.sign).toHaveBeenCalledWith(expect.objectContaining({ source_kind: 'empty', document: expect.objectContaining({ url: '' }) })));
});

it('forwards the exact owned upload reference and source path', async () => {
    mocks.sign.mockRejectedValue(new Error('synthetic stop'));
    render(<Word data={{ key: 'server-key', path: '/bucket/tmp/upload.docx', preview_upload_ref: 'issued-upload-ref' }} />);
    await waitFor(() => expect(mocks.sign).toHaveBeenCalledWith(expect.objectContaining({ preview_upload_ref: 'issued-upload-ref', document: expect.objectContaining({ url: '/bucket/tmp/upload.docx' }) })));
});

it('does not construct an editor after unmount while issuance is pending', async () => {
    let resolve: (value: { token: string }) => void = () => {};
    mocks.sign.mockReturnValue(new Promise(value => { resolve = value; }));
    const { unmount } = render(<Word data={{ key: 'server-key', path: 'https://minio.test/bucket/report/a.docx' }} />);
    unmount();
    await act(async () => { resolve({ token: 'synthetic-issued-token' }); });
    expect(mocks.editor).not.toHaveBeenCalled();
});

it('boots only with the issued token and destroys the editor on unmount', async () => {
    mocks.sign.mockResolvedValue({ token: 'synthetic-issued-token', config: { documentType: 'word', document: { key: 'server-key', fileType: 'docx', url: 'https://canonical.test/doc.docx' }, editorConfig: { callbackUrl: 'https://public.test/bisheng/api/v1/report/callback' } } });
    const { unmount } = render(<Word data={{ key: 'server-key', path: 'https://minio.test/bucket/report/a.docx' }} />);
    await waitFor(() => expect(mocks.editor).toHaveBeenCalledTimes(1));
    expect(mocks.sign.mock.calls[0][0]).not.toHaveProperty('source_kind');
    expect(mocks.sign.mock.calls[0][0]).not.toHaveProperty('preview_upload_ref');
    expect(mocks.editor).toHaveBeenCalledWith('bsoffice', {
        token: 'synthetic-issued-token', documentType: 'word',
        document: { key: 'server-key', fileType: 'docx', url: 'https://canonical.test/doc.docx' },
        editorConfig: { callbackUrl: 'https://public.test/bisheng/api/v1/report/callback' },
    });
    unmount();
    expect(mocks.destroy).toHaveBeenCalledTimes(1);
});
