import request from '../request';
import type { TrainingDataType, TrainingFile } from './finetuneV2';

export interface DatasetConnection {
    endpoint: string; username?: string; password?: string; tls?: boolean; host_fingerprint?: string;
    bucket?: string; access_key?: string; secret_key?: string; session_token?: string; region?: string;
}
export type RemoteDatasetSource = 'ftp' | 'sftp' | 's3';
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
    const file = await request.post<unknown, TrainingFile>('/api/v1/finetune/datasets/import', data, { timeout: 600000, showError: false });
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
