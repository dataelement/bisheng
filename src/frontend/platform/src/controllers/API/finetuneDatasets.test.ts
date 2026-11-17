import { beforeEach, describe, expect, it, vi } from 'vitest';
import request from '../request';
import { getTrainingDatasetMedia, getTrainingDatasetPreview, importTrainingDataset, listTrainingDatasets } from './finetuneDatasets';

vi.mock('../request', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
const file = { id: 'dataset1', version_id: 'version1', name: 'examples', num: 999, url: 'object/key', dataset_report: { validated: true, data_type: 'text', samples: 8, media: 0, sha256: 'abc' } };
beforeEach(() => vi.clearAllMocks());
describe('dataset API contract', () => {
    it('uses server sample counts and excludes invalid or incompatible list entries', async () => {
        vi.mocked(request.get).mockResolvedValue({ data: [file, { ...file, id: '' }, { ...file, dataset_report: { ...file.dataset_report, validated: false } }, { ...file, dataset_report: { ...file.dataset_report, data_type: 'video_text' } }], total: 4 });
        expect(await listTrainingDatasets('text', 2)).toEqual({ data: [{ ...file, num: 8 }], total: 4 });
        expect(request.get).toHaveBeenCalledWith('/api/v1/finetune/datasets', { params: { data_type: 'text', page: 2, limit: 20 } });
    });
    it('passes credentials in the request body only and rejects unvalidated imports', async () => {
        const data = { name: 'test', data_type: 'text' as const, source: 'ftp' as const, connection: { endpoint: 'ftp://files.example.com', password: 'secret' }, manifest_path: 'train.json', media_root: '' };
        vi.mocked(request.post).mockResolvedValueOnce(file).mockResolvedValueOnce({ ...file, dataset_report: { ...file.dataset_report, validated: false } });
        expect(await importTrainingDataset(data)).toEqual({ ...file, num: 8 });
        expect(request.post).toHaveBeenCalledWith('/api/v1/finetune/datasets/import', data, { timeout: 600000 });
        await expect(importTrainingDataset(data)).rejects.toThrow('Dataset validation did not complete');
    });
    it('uses the selected immutable version for preview and authenticated blob downloads', async () => {
        const url = '/api/v1/finetune/datasets/version1/media?path=images%2Fone.png';
        vi.mocked(request.get).mockResolvedValueOnce({ samples: [] }).mockResolvedValueOnce(new Blob(['image']));
        await getTrainingDatasetPreview('version1'); await getTrainingDatasetMedia('version1', url);
        expect(request.get).toHaveBeenNthCalledWith(1, '/api/v1/finetune/datasets/version1/preview');
        expect(request.get).toHaveBeenNthCalledWith(2, url, { responseType: 'blob' });
    });
    it('does not send platform authentication to remote or unrelated media URLs', async () => {
        for (const url of ['https://other.example.com/image.png', '//other.example.com/image.png', '/api/v1/finetune/datasets/other/media?path=image.png']) {
            await expect(getTrainingDatasetMedia('version1', url)).rejects.toThrow('Invalid dataset media URL');
        }
        expect(request.get).not.toHaveBeenCalled();
    });
});
