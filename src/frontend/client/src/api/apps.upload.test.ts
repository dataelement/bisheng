import request from './request';
import { uploadChatFile, uploadFileWithProgress } from './apps';

jest.mock('./request', () => ({ __esModule: true, default: { post: jest.fn() } }));
jest.mock('~/utils', () => ({ generateUUID: () => 'synthetic-file-id' }));
jest.mock('@bisheng/chat/core', () => ({ historyForHost: jest.fn() }));
jest.mock('~/utils/mediaAttachmentUtils', () => ({ normalizeMinioObjectPath: (value: string) => value }));

beforeEach(() => jest.mocked(request.post).mockReset());

it.each([
    ['workstation', '/api/v1/workstation/files'],
    ['linsight', '/api/v1/linsight/workbench/upload-file'],
    [undefined, '/api/v1/knowledge/upload'],
] as const)('uses the matching upload contract for %s', async (mode, endpoint) => {
    const result = { status_code: 200, data: { filepath: '/tmp-dir/workstation-uploads/probe.txt' } };
    jest.mocked(request.post).mockResolvedValue(result);
    const controller = new AbortController();
    const file = new File(['Synthetic upload probe'], 'probe.txt', { type: 'text/plain' });
    await expect(uploadChatFile(null, file, jest.fn(), mode, undefined, controller.signal)).resolves.toBe(result);
    const [url, payload, options] = jest.mocked(request.post).mock.calls[0];
    expect(url).toBe(endpoint);
    const uploaded = (payload as FormData).get('file') as File;
    expect(uploaded.name).toBe(file.name);
    expect(uploaded.size).toBe(file.size);
    expect(uploaded.type).toBe(file.type);
    expect((payload as FormData).get('file_id')).toBe(mode ? 'synthetic-file-id' : null);
    expect(options?.signal).toBe(controller.signal);
});

it('propagates an upload failure without publishing completion', async () => {
    const error = new Error('synthetic network failure');
    jest.mocked(request.post).mockRejectedValue(error);
    const progress = jest.fn();
    await expect(uploadFileWithProgress(new File(['probe'], 'probe.txt'), progress, 'knowledge', undefined)).rejects.toBe(error);
    expect(progress).not.toHaveBeenCalledWith(100);
});

it('publishes completion only after a successful knowledge upload', async () => {
    const data = { file_path: '/tmp-dir/probe.txt' };
    jest.mocked(request.post).mockResolvedValue({ status_code: 200, data });
    const progress = jest.fn();
    await expect(uploadFileWithProgress(new File(['probe'], 'probe.txt'), progress, 'knowledge', undefined)).resolves.toBe(data);
    expect(progress).toHaveBeenCalledWith(100);
});
