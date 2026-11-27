import request from '../request';
import type { TrainingDataType, TrainingFile } from './finetuneV2';

export interface DatasetConnection {
    endpoint: string; username?: string; password?: string; tls?: boolean; host_fingerprint?: string;
    bucket?: string; access_key?: string; secret_key?: string; session_token?: string; region?: string;
}
export type RemoteDatasetSource = 'ftp' | 'sftp' | 's3';
export type DatasetCategory = 'legacy' | TrainingDataType;
export interface DatasetImportRequest {
    name: string; data_type: TrainingDataType; source: RemoteDatasetSource; connection: DatasetConnection;
    manifest_path?: string; manifest_text?: string; manifest_filename?: string; media_root: string;
}
export interface DatasetSample {
    messages: { role: string; content: string }[];
    media: { url: string; type: 'image' | 'video'; name: string }[];
}
export async function listTrainingDatasets(data_type: TrainingDataType, page = 1) {
    const result = await request.get<unknown, { data: TrainingFile[]; total: number }>(
        '/api/v1/finetune/datasets', { params: { data_type, page, limit: 20 } });
    return { ...result, data: result.data.filter(file => file.id && file.dataset_report?.validated && file.dataset_report.data_type === data_type)
        .map(file => ({ ...file, num: file.dataset_report.samples })) };
}
export async function importTrainingDataset(data: DatasetImportRequest) {
    const file = await request.post<unknown, TrainingFile>('/api/v1/finetune/dataset-catalog/import', data, { timeout: 600000, showError: false });
    if (!file?.dataset_report?.validated) throw new Error('Dataset validation did not complete');
    return { ...file, num: file.dataset_report.samples };
}
export const getTrainingDatasetPreview = (versionId: string) => request.get<unknown, { samples: DatasetSample[] }>(
    `/api/v1/finetune/datasets/${encodeURIComponent(versionId)}/preview`);
export function getTrainingDatasetMedia(versionId: string, url: string) {
    const prefix = `/api/v1/finetune/datasets/${encodeURIComponent(versionId)}/media?`;
    if (!url.startsWith(prefix)) return Promise.reject(new Error('Invalid dataset media URL'));
    return request.get<unknown, Blob>(url, { responseType: 'blob' });
}


export interface CatalogDataset {
    id: string; name: string; url: string; data_type: DatasetCategory; source_type: string;
    version_id?: string; user_name?: string; create_time: string; update_time: string;
    dataset_report?: TrainingFile['dataset_report'];
}
export function listDatasetCatalog(params: { data_type?: DatasetCategory; keyword?: string; page?: number; limit?: number }) {
    return request.get<unknown, { data: CatalogDataset[]; total: number }>('/api/v1/finetune/dataset-catalog', { params });
}
export function uploadCatalogDataset(file: File, data_type: TrainingDataType, name: string, onProgress?: (percent: number) => void) {
    const body = new FormData(); body.append('files', file); body.append('data_type', data_type); body.append('name', name);
    return request.post<unknown, TrainingFile>('/api/v1/finetune/dataset-catalog/files', body, { timeout: 0, showError: false,
        onUploadProgress: event => onProgress?.(Math.round((event.loaded / (event.total || file.size)) * 100)) });
}
export const convertCatalogDataset = (id: string) => request.post(`/api/v1/finetune/dataset-catalog/${encodeURIComponent(id)}/convert`, undefined, { timeout: 600000 });
export const deleteCatalogDataset = (id: string) => request.delete(`/api/v1/finetune/dataset-catalog/${encodeURIComponent(id)}`);
export const downloadCatalogDataset = (id: string) => request.get<unknown, { url: string }>(`/api/v1/finetune/dataset-catalog/${encodeURIComponent(id)}/download`);
export function datasetPreviewPath(id: string, kind: 'version' | 'catalog' | 'temporary') {
    const segment = kind === 'temporary' ? 'task-uploads' : kind === 'catalog' ? 'dataset-catalog' : 'datasets';
    return `/api/v1/finetune/${segment}/${encodeURIComponent(id)}`;
}
export const getDatasetPreview = (id: string, kind: 'version' | 'catalog' | 'temporary') =>
    request.get<unknown, { samples: DatasetSample[] }>(`${datasetPreviewPath(id, kind)}/preview`);
export function getDatasetPreviewMedia(id: string, kind: 'version' | 'catalog' | 'temporary', url: string) {
    if (!url.startsWith(`${datasetPreviewPath(id, kind)}/media?`)) return Promise.reject(new Error('Invalid dataset media URL'));
    return request.get<unknown, Blob>(url, { responseType: 'blob' });
}

export async function importQADataset(name: string, qa_list: number[]) {
    const file = await request.post<unknown, TrainingFile>('/api/v1/finetune/job/file/preset', { name, qa_list }, { timeout: 600000, showError: false });
    if (!file?.dataset_report?.validated || file.dataset_report.data_type !== 'text') throw new Error('QA dataset validation did not complete');
    return { ...file, num: file.dataset_report.samples };
}
