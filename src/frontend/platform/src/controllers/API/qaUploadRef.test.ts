import { afterEach, expect, it, vi } from 'vitest';
import request from '@/controllers/request';
import { getQaFilePreview, postImportQaFile } from './index';

vi.mock('@/controllers/request', () => ({ default: { post: vi.fn() } }));
afterEach(() => vi.clearAllMocks());

it('sends the exact upload-issued reference alongside the preview path', async () => {
    await getQaFilePreview('kb-1', { url: 'tmp/qa.xlsx', size: 10, preview_upload_ref: 'issued-ref-A' });
    expect(request.post).toHaveBeenCalledWith('/api/v1/knowledge/qa/preview/kb-1', {
        file_url: 'tmp/qa.xlsx', size: 10, offset: undefined, preview_upload_ref: 'issued-ref-A',
    });
});

it('keeps import references parallel to file_list, without deriving them from paths', async () => {
    await postImportQaFile('kb-1', { url: 'tmp/qa.xlsx', preview_upload_ref: 'issued-ref-B' });
    expect(request.post).toHaveBeenCalledWith('/api/v1/knowledge/qa/import/kb-1', {
        file_list: ['tmp/qa.xlsx'], preview_upload_refs: ['issued-ref-B'],
    });
});
