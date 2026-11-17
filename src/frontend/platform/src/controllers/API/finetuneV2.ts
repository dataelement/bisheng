import request from '../request';

export type TrainingDataType = 'text' | 'image_text' | 'video_text';
export interface TrainingService { id: number; server: string; sft_endpoint: string }
export interface TrainingCapability {
    capability_id: string; model_name: string; input_types: TrainingDataType[];
    training_methods: string[]; base_model_id?: number; registered?: boolean;
    validation_status: string; blocked_reason?: string; model_ready?: boolean; ready?: boolean;
    parameter_schema?: Record<string, unknown>;
}
export interface DatasetReport {
    data_type: TrainingDataType; samples: number; media: number; sha256: string; validated: boolean;
}
export interface TrainingFile { id: string; url: string; name: string; num: number; dataset_report: DatasetReport; version_id?: string; create_time?: string }
export interface TrainingRequest {
    contract_version: 2; data_type: TrainingDataType; server: number; base_model: number;
    capability_id: string; method: 'lora'; model_name: string; extra_params: Record<string, number>;
    train_data: TrainingFile[]; preset_data: never[]; dataset_report: { files: DatasetReport[] };
}
export interface TrainingTask {
    id: string; model_name: string; base_model_name: string; status: number; contract_version?: number;
    data_type?: TrainingDataType; stage?: string; reason?: string; create_time: string;
    user_name?: string; train_data?: TrainingFile[]; preset_data?: TrainingFile[];
    artifact_report?: { complete?: boolean; files?: unknown[]; [key: string]: unknown };
    inference_validation?: Record<string, unknown>; report?: Record<string, unknown>;
    extra_params?: Record<string, unknown>; capability_snapshot?: Record<string, unknown>;
}
export interface TrainingInfo {
    finetune: TrainingTask; log?: unknown; train_log?: string;
    report?: Record<string, unknown>; config_snapshot?: Record<string, unknown>; loss_data?: unknown[];
}
export interface TrainingPreflight { passed: boolean; checks: { name: string; passed: boolean; detail?: unknown }[] }
export const listTrainingServices = () => request.get<unknown, TrainingService[]>('/api/v1/server/list_server');
export const addTrainingService = (server: string, sft_endpoint: string) => request.post<unknown, TrainingService>(
    '/api/v1/server/add', { server, sft_endpoint, endpoint: '', remark: '' });
export const deleteTrainingService = (id: number) => request.delete(`/api/v1/server/${id}`);
export const discoverTrainingModels = (server_id: number) => request.get<unknown, { models: TrainingCapability[] }>(
    '/api/v1/finetune/capabilities', { params: { server_id } });
export const preflightTraining = (data: TrainingRequest) => request.post<unknown, TrainingPreflight>(
    '/api/v1/finetune/preflight', { server: data.server, base_model: data.base_model, capability_id: data.capability_id,
        data_type: data.data_type, method: data.method, parameters: data.extra_params });
export const submitTraining = (data: TrainingRequest) => request.post<unknown, TrainingTask>('/api/v1/finetune/job', data);
export async function uploadTrainingFile(file: File): Promise<TrainingFile> {
    const data = new FormData(); data.append('files', file);
    const files = await request.post<unknown, TrainingFile[]>('/api/v1/finetune/job/file', data);
    if (!files[0]?.dataset_report?.validated) throw new Error('Dataset validation did not complete');
    return { ...files[0], num: files[0].dataset_report.samples };
}
export const getTrainingInfo = (jobId: string) => request.get<unknown, TrainingInfo>(
    '/api/v1/finetune/job/info', { params: { job_id: jobId } });
export const cancelTraining = (jobId: string) => request.post('/api/v1/finetune/job/cancel', null, { params: { job_id: jobId } });
export async function uploadValidationMedia(jobId: string, file: File) {
    const data = new FormData(); data.append('file', file);
    return request.post<unknown, { url: string }>(`/api/v1/finetune/job/${encodeURIComponent(jobId)}/media`, data);
}
export const runTrainingInference = (jobId: string, data: { prompt: string; media_url?: string; baseline: boolean; generation: { max_new_tokens: number } }) =>
    request.post<unknown, Record<string, unknown>>(`/api/v1/finetune/job/${encodeURIComponent(jobId)}/validate`, data, { timeout: 600000 });
