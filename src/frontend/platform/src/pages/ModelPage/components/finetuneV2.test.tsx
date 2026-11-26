import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { CreateTask } from './CreateTask';
import { FinetuneValidation } from './FinetuneValidation';
import { CreateTaskList } from './CreateTaskList';
import { ApiError } from '@bisheng/api-client';
import { DatasetImportDialog, safeDatasetImportError, validDatasetEndpoint } from './DatasetImportDialog';
import { getTrainingDatasetPreview, getTrainingDatasetMedia, importTrainingDataset, listTrainingDatasets, uploadCatalogDataset, getDatasetPreview } from '@/controllers/API/finetuneDatasets';
import { compatibleTrainingFiles, selectableTrainingModels, validTrainingParameters } from './finetuneHelpers';
import type { TrainingCapability, TrainingFile, TrainingTask } from '@/controllers/API/finetuneV2';
import { discoverTrainingModels, listTrainingServices, preflightTraining, submitTraining, runTrainingInference, uploadTrainingFile, uploadValidationMedia } from '@/controllers/API/finetuneV2';

vi.mock('@/controllers/API/finetuneV2', () => ({ listTrainingServices: vi.fn(), discoverTrainingModels: vi.fn(), preflightTraining: vi.fn(), submitTraining: vi.fn(), runTrainingInference: vi.fn(), uploadValidationMedia: vi.fn(), uploadTrainingFile: vi.fn() }));
vi.mock('@/controllers/API/finetuneDatasets', () => ({ listTrainingDatasets: vi.fn(), importTrainingDataset: vi.fn(), getTrainingDatasetPreview: vi.fn(), getTrainingDatasetMedia: vi.fn(), uploadCatalogDataset: vi.fn(), getDatasetPreview: vi.fn(), getDatasetPreviewMedia: vi.fn() }));
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise.catch(() => undefined) }));
const report = { data_type: 'video_text' as const, samples: 6, media: 6, sha256: 'abc', validated: true };
const dataset: TrainingFile = { id: 'data1', url: 'object/key', name: 'video.zip', num: 6, dataset_report: report };
const task: TrainingTask = { id: 'task1', model_name: 'video-v1', base_model_name: 'Qwen2.5-VL-3B-Instruct', status: 4, contract_version: 2, data_type: 'video_text', create_time: '' };

beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listTrainingDatasets).mockResolvedValue({ data: [], total: 0 });
    vi.mocked(getTrainingDatasetPreview).mockResolvedValue({ samples: [] });
    vi.mocked(getDatasetPreview).mockResolvedValue({ samples: [] });
    vi.mocked(uploadCatalogDataset).mockResolvedValue(dataset);
    URL.createObjectURL = vi.fn(() => 'blob:preview'); URL.revokeObjectURL = vi.fn();
});
describe('training capability and dataset boundaries', () => {
    it('only enables registered, ready, validated models matching the modality and method', () => {
        const valid: TrainingCapability = { capability_id: 'vl', model_name: 'VL', input_types: ['video_text'], training_methods: ['lora'], base_model_id: 1, registered: true, validation_status: 'gpu_smoke_passed' };
        expect(selectableTrainingModels([valid, { ...valid, capability_id: '' }, { ...valid, model_ready: false }, { ...valid, ready: false }, { ...valid, validation_status: 'unverified' }, { ...valid, base_model_id: undefined }, { ...valid, training_methods: ['qlora'] }], 'video_text')).toEqual([valid]);
        expect(selectableTrainingModels([valid], 'text')).toEqual([]);
        expect(compatibleTrainingFiles([dataset], 'text')).toEqual([]);
    });
    it('uses the authoritative upload sample count and report', async () => {
        vi.mocked(uploadTrainingFile).mockResolvedValue(dataset);
        const changed = vi.fn(); render(<CreateTaskList dataType="video_text" files={[]} onChange={changed} />);
        fireEvent.click(screen.getByRole('button', { name: 'finetune.temporaryUpload' }));
        fireEvent.change(screen.getByLabelText('finetune.uploadDataset'), { target: { files: [new File(['data'], 'video.zip')] } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        await waitFor(() => expect(changed).toHaveBeenCalledWith([dataset]));
    });
    it('does not accept an image dataset for a video task', async () => {
        vi.mocked(uploadTrainingFile).mockResolvedValue({ ...dataset, dataset_report: { ...report, data_type: 'image_text' } });
        const changed = vi.fn(); render(<CreateTaskList dataType="video_text" files={[]} onChange={changed} />);
        fireEvent.click(screen.getByRole('button', { name: 'finetune.temporaryUpload' }));
        fireEvent.change(screen.getByLabelText('finetune.uploadDataset'), { target: { files: [new File(['data'], 'images.zip')] } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('finetune.datasetTypeMismatch');
        expect(changed).not.toHaveBeenCalled();
    });
});
describe('new sample inference', () => {
    it('uploads the selected video and calls the real API separately for baseline and adapter', async () => {
        vi.mocked(uploadValidationMedia).mockResolvedValue({ url: 'tenant/task/test.mp4' });
        vi.mocked(runTrainingInference).mockResolvedValueOnce({ response: 'blue right' }).mockResolvedValueOnce({ response: 'blue left' });
        render(<FinetuneValidation task={task} />);
        fireEvent.change(screen.getByLabelText('finetune.validationPrompt'), { target: { value: 'What direction?' } });
        const file = new File(['video'], 'new.mp4', { type: 'video/mp4' });
        fireEvent.change(screen.getByLabelText('finetune.newVideo'), { target: { files: [file] } });
        fireEvent.click(screen.getByLabelText('finetune.compareBase'));
        fireEvent.click(screen.getByRole('button', { name: 'finetune.runReloadInference' }));
        await screen.findByText('blue left');
        expect(screen.getByText('blue right')).toBeInTheDocument();
        expect(uploadValidationMedia).toHaveBeenCalledWith('task1', file);
        expect(runTrainingInference).toHaveBeenNthCalledWith(1, 'task1', expect.objectContaining({ baseline: true, media_url: 'tenant/task/test.mp4' }));
        expect(runTrainingInference).toHaveBeenNthCalledWith(2, 'task1', expect.objectContaining({ baseline: false, media_url: 'tenant/task/test.mp4' }));
        expect(screen.getByText('finetune.inferenceQualityHint')).toBeInTheDocument();
    });
    it('blocks media inference without a new file and preserves a failure without fabricated answers', async () => {
        render(<FinetuneValidation task={task} />);
        fireEvent.change(screen.getByLabelText('finetune.validationPrompt'), { target: { value: 'Question' } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.runReloadInference' }));
        expect(screen.getByRole('alert')).toHaveTextContent('finetune.validationInputRequired');
        expect(runTrainingInference).not.toHaveBeenCalled();
        vi.mocked(uploadValidationMedia).mockRejectedValue(new Error('upload failed'));
        fireEvent.change(screen.getByLabelText('finetune.newVideo'), { target: { files: [new File(['x'], 'bad.mp4')] } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.runReloadInference' }));
        await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('finetune.inferenceFailed'));
        expect(runTrainingInference).not.toHaveBeenCalled();
    });
});


describe('formal single-page task submission', () => {
    it('retries an empty model name with a decimal version and preflights before submission', async () => {
        const model: TrainingCapability = { capability_id: 'qwen3', model_name: 'Qwen3-0.6B', input_types: ['text'], training_methods: ['lora'], base_model_id: 3, registered: true, validation_status: 'gpu_smoke_passed' };
        vi.mocked(listTrainingServices).mockResolvedValue([{ id: 7, server: 'Customer training' }]);
        vi.mocked(discoverTrainingModels).mockResolvedValue({ models: [model] });
        const textData: TrainingFile = { ...dataset, name: 'text.zip', num: 8, dataset_report: { ...report, data_type: 'text', samples: 8, media: 0 } };
        vi.mocked(uploadTrainingFile).mockResolvedValue(textData);
        vi.mocked(preflightTraining).mockResolvedValue({ passed: true, checks: [] });
        vi.mocked(submitTraining).mockResolvedValue({ ...task, id: 'new-task' });
        const created = vi.fn();
        render(<CreateTask rtClick={vi.fn()} gpuClick={vi.fn()} onCancel={vi.fn()} onCreate={created} />);
        const user = userEvent.setup();
        await user.click(screen.getByRole('combobox', { name: 'finetune.rtService' }));
        await user.click(await screen.findByRole('option', { name: 'Customer training' }));
        await waitFor(() => expect(discoverTrainingModels).toHaveBeenCalledWith(7));
        await user.click(screen.getByRole('combobox', { name: 'finetune.baseModel' }));
        await user.click(await screen.findByRole('option', { name: 'Qwen3-0.6B' }));
        fireEvent.click(screen.getByRole('button', { name: 'finetune.temporaryUpload' }));
        fireEvent.change(screen.getByLabelText('finetune.uploadDataset'), { target: { files: [new File(['data'], 'text.zip')] } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        await screen.findByText('text.zip');
        fireEvent.change(screen.getByLabelText('finetune.param_max_steps'), { target: { value: '-1' } });
        await user.click(screen.getByRole('button', { name: 'finetune.checkAndCreate' }));
        expect(screen.getByRole('alert')).toHaveTextContent('finetune.modelNameHint');
        expect(preflightTraining).not.toHaveBeenCalled();
        expect(submitTraining).not.toHaveBeenCalled();
        fireEvent.change(screen.getByLabelText('finetune.finetuneModelName'), { target: { value: 'quwe3-0.6b-001' } });
        await user.click(screen.getByRole('button', { name: 'finetune.checkAndCreate' }));
        await waitFor(() => expect(created).toHaveBeenCalledWith('new-task'));
        expect(submitTraining).toHaveBeenCalledWith(expect.objectContaining({ model_name: 'quwe3-0.6b-001', server: 7, base_model: 3, capability_id: 'qwen3', data_type: 'text', train_data: [textData], extra_params: expect.objectContaining({ max_steps: -1, cutoff_len: 1024 }) }));
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(vi.mocked(preflightTraining).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(submitTraining).mock.invocationCallOrder[0]);
    });
});


describe('single-package and epoch mode contract', () => {
    it('replaces an existing dataset when a new package is uploaded', async () => {
        vi.mocked(uploadTrainingFile).mockResolvedValue(dataset);
        const old = { ...dataset, id: 'old', dataset_report: { ...report, sha256: 'old' } };
        const changed = vi.fn();
        render(<CreateTaskList dataType="video_text" files={[old]} onChange={changed} />);
        fireEvent.click(screen.getByRole('button', { name: 'finetune.temporaryUpload' }));
        fireEvent.change(screen.getByLabelText('finetune.uploadDataset'), { target: { files: [new File(['data'], 'video.zip')] } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        await waitFor(() => expect(changed).toHaveBeenCalledWith([dataset]));
    });
    it('allows epoch mode and positive integer steps, rejecting zero and fractional step counts', () => {
        const parameters = { max_steps: -1, num_train_epochs: 2, learning_rate: 0.0001 };
        expect(validTrainingParameters(parameters)).toBe(true);
        expect(validTrainingParameters({ ...parameters, max_steps: 8 })).toBe(true);
        for (const value of [0, -2, 1.5, NaN, Infinity]) expect(validTrainingParameters({ ...parameters, max_steps: value })).toBe(false);
        expect(validTrainingParameters({ ...parameters, learning_rate: -1 })).toBe(false);
    });
});

describe('reusable datasets and remote imports', () => {
    it('selects an existing validated version and fetches protected media through the API', async () => {
        const saved = { ...dataset, version_id: 'version1' };
        vi.mocked(listTrainingDatasets).mockResolvedValue({ data: [saved], total: 1 });
        vi.mocked(getTrainingDatasetPreview).mockResolvedValue({ samples: [{ messages: [{ role: 'user', content: 'Stored sample' }], media: [{ name: 'clip.mp4', type: 'video', url: '/api/v1/finetune/datasets/version1/media?path=clip.mp4' }] }] });
        vi.mocked(getTrainingDatasetMedia).mockResolvedValue(new Blob(['media']));
        const changed = vi.fn();
        const view = render(<CreateTaskList dataType="video_text" files={[]} onChange={changed} />);
        const user = userEvent.setup();
        await waitFor(() => expect(listTrainingDatasets).toHaveBeenCalledWith('video_text', 1));
        await user.click(screen.getByRole('combobox', { name: 'finetune.datasetExistingVersion' }));
        await user.click(await screen.findByRole('option', { name: 'video.zip · version1' }));
        expect(changed).toHaveBeenCalledWith([saved]);
        view.rerender(<CreateTaskList dataType="video_text" files={[saved]} onChange={changed} />);
        await screen.findByText('Stored sample');
        expect(getTrainingDatasetMedia).toHaveBeenCalledWith('version1', '/api/v1/finetune/datasets/version1/media?path=clip.mp4');
        view.unmount();
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview');
    });
    it('submits an FTP manifest path and one media root without storing credentials', async () => {
        vi.mocked(importTrainingDataset).mockResolvedValue(dataset);
        const imported = vi.fn(); const closed = vi.fn();
        const storage = vi.spyOn(Storage.prototype, 'setItem');
        render(<DatasetImportDialog dataType="video_text" onImported={imported} onClose={closed} />);
        fireEvent.click(screen.getByLabelText('finetune.datasetSource_ftp'));
        for (const [label, value] of Object.entries({ datasetImportName: 'clips', datasetEndpoint: 'ftp://files.example.com:21', datasetConnection_username: 'reader', datasetConnection_password: 'secret-value', datasetManifestPath: 'datasets/train.json', datasetMediaRoot: 'datasets/' })) {
            fireEvent.change(screen.getByLabelText(`finetune.${label}`), { target: { value } });
        }
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        await waitFor(() => expect(imported).toHaveBeenCalledWith(dataset));
        expect(importTrainingDataset).toHaveBeenCalledWith({ name: 'clips', data_type: 'video_text', source: 'ftp', connection: { endpoint: 'ftp://files.example.com:21', username: 'reader', password: 'secret-value' }, manifest_path: 'datasets/train.json', media_root: 'datasets/' });
        expect(closed).toHaveBeenCalledOnce();
        expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
    });
    it('submits a local JSONL manifest with S3 connection details only once', async () => {
        vi.mocked(importTrainingDataset).mockResolvedValue(dataset);
        const imported = vi.fn(); render(<DatasetImportDialog dataType="video_text" onImported={imported} onClose={vi.fn()} />);
        fireEvent.click(screen.getByLabelText('finetune.datasetSource_s3'));
        for (const [label, value] of Object.entries({ datasetImportName: 'clips', datasetEndpoint: 'https://objects.example.com', datasetConnection_bucket: 'training', datasetConnection_access_key: 'key', datasetConnection_secret_key: 'secret', datasetMediaRoot: 'examples/' })) {
            fireEvent.change(screen.getByLabelText(`finetune.${label}`), { target: { value } });
        }
        fireEvent.click(screen.getByLabelText('finetune.datasetManifest_local'));
        const manifest = '{"videos":["clips/one.mp4"],"messages":[]}';
        const file = new File([manifest], 'train.jsonl'); Object.defineProperty(file, 'text', { value: async () => manifest });
        fireEvent.change(screen.getByLabelText('finetune.datasetLocalManifest'), { target: { files: [file] } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        await waitFor(() => expect(imported).toHaveBeenCalled());
        expect(importTrainingDataset).toHaveBeenCalledWith(expect.objectContaining({ source: 's3', manifest_filename: 'train.jsonl', manifest_text: manifest, media_root: 'examples/', connection: { endpoint: 'https://objects.example.com', bucket: 'training', access_key: 'key', secret_key: 'secret' } }));
        expect(vi.mocked(importTrainingDataset).mock.calls[0][0]).not.toHaveProperty('manifest_path');
    });
    it('keeps import failures visible without accepting data or echoing secrets', async () => {
        vi.mocked(importTrainingDataset).mockRejectedValue(new Error('Cannot connect: secret-value'));
        const imported = vi.fn(); render(<DatasetImportDialog dataType="video_text" onImported={imported} onClose={vi.fn()} />);
        fireEvent.click(screen.getByLabelText('finetune.datasetSource_ftp'));
        for (const [label, value] of Object.entries({ datasetImportName: 'clips', datasetEndpoint: 'ftp://files.example.com', datasetConnection_password: 'secret-value', datasetManifestPath: 'train.json' })) {
            fireEvent.change(screen.getByLabelText(`finetune.${label}`), { target: { value } });
        }
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('finetune.datasetImportFailed Cannot connect: ••••');
        expect(imported).not.toHaveBeenCalled();
    });
    it('requires an SFTP username and sends the optional host fingerprint', async () => {
        vi.mocked(importTrainingDataset).mockResolvedValue(dataset);
        const imported = vi.fn(); render(<DatasetImportDialog dataType="video_text" onImported={imported} onClose={vi.fn()} />);
        fireEvent.click(screen.getByLabelText('finetune.datasetSource_sftp'));
        for (const [label, value] of Object.entries({ datasetImportName: 'clips', datasetEndpoint: 'sftp://files.example.com:22', datasetConnection_password_required: 'secret-value', datasetManifestPath: 'train.json' })) {
            fireEvent.change(screen.getByLabelText(`finetune.${label}`), { target: { value } });
        }
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('finetune.datasetConnectionRequired');
        expect(importTrainingDataset).not.toHaveBeenCalled();
        fireEvent.change(screen.getByLabelText('finetune.datasetConnection_username_required'), { target: { value: 'reader' } });
        fireEvent.change(screen.getByLabelText('finetune.datasetConnection_host_fingerprint'), { target: { value: 'SHA256:abc' } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        await waitFor(() => expect(imported).toHaveBeenCalled());
        expect(importTrainingDataset).toHaveBeenCalledWith(expect.objectContaining({ source: 'sftp', connection: { endpoint: 'sftp://files.example.com:22', username: 'reader', password: 'secret-value', host_fingerprint: 'SHA256:abc' } }));
        expect(validDatasetEndpoint('sftp://files.example.com', 'sftp')).toBe(true);
        expect(validDatasetEndpoint('ftp://files.example.com', 'sftp')).toBe(false);
    });
    it('rejects endpoint credentials, paths and query strings and never serializes raw errors', () => {
        expect(validDatasetEndpoint('ftp://files.example.com:21', 'ftp')).toBe(true);
        expect(validDatasetEndpoint('ftps://files.example.com', 'ftp')).toBe(true);
        expect(validDatasetEndpoint('https://objects.example.com:9000', 's3')).toBe(true);
        for (const endpoint of ['ftp://user:password@files.example.com', 'ftp://files.example.com/path', 'ftp://files.example.com?password=secret', 'https://files.example.com']) expect(validDatasetEndpoint(endpoint, 'ftp')).toBe(false);
        expect(safeDatasetImportError({ config: { password: 'secret' } }, { endpoint: '' }, 'Import failed')).toBe('Import failed');
        const rejected = new ApiError({}, { message: 'Package invalid.', envelope: { status_code: 10129, status_message: 'Image cannot be decoded: images/a.png (secret)' } });
        expect(safeDatasetImportError(rejected, { endpoint: '', password: 'secret' }, 'Import failed', 'Details: ')).toBe('Import failed Package invalid. Details: Image cannot be decoded: images/a.png (••••)');
    });
    it('shows list failures and retries without inventing a dataset', async () => {
        vi.mocked(listTrainingDatasets).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: [], total: 0 });
        render(<CreateTaskList dataType="text" files={[]} onChange={vi.fn()} />);
        expect(await screen.findByRole('alert')).toHaveTextContent('finetune.datasetListFailed');
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetRefresh' }));
        await screen.findByText('finetune.datasetEmpty');
    });
});

const remoteReport = { data_type: 'image_text' as const, samples: 3, media: 3, sha256: 'plan', validated: true, delivery: 'remote' as const, total_bytes: 3 * 1024 * 1024 * 1024,
    remote: { type: 'sftp' as const, endpoint: 'sftp://files.example.com', username: 'reader', layout: 'manifest' as const, path: 'datasets/train.json', media_root: 'datasets' } };
const remoteDataset: TrainingFile = { id: 'remote1', version_id: 'remote1', url: 'x.plan.json', name: 'receipts', num: 3, dataset_report: { ...remoteReport, preview_url: 'x.plan.json.preview.zip' } };

describe('remote sources and large local packages', () => {
    it('rejects local packages over 2 GB and JSON files over 200 MB before uploading', async () => {
        render(<DatasetImportDialog dataType="text" onImported={vi.fn()} onClose={vi.fn()} />);
        for (const [name, size] of [['big.zip', 2049 * 1024 * 1024], ['big.jsonl', 201 * 1024 * 1024]] as const) {
            const file = new File(['x'], name); Object.defineProperty(file, 'size', { value: size });
            fireEvent.change(screen.getByLabelText('finetune.uploadDataset'), { target: { files: [file] } });
            fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
            expect(await screen.findByRole('alert')).toHaveTextContent('finetune.datasetUploadSizeLimit');
        }
        expect(uploadTrainingFile).not.toHaveBeenCalled();
    });
    it('describes where a remote version lives and skips the preview for a remote ZIP', async () => {
        const zip = { ...remoteDataset, dataset_report: { ...remoteReport, remote: { ...remoteReport.remote, layout: 'zip' as const, path: 'datasets/all.zip' } } };
        render(<CreateTaskList dataType="image_text" files={[zip]} onChange={vi.fn()} />);
        expect(screen.getByText('finetune.datasetRemoteZipChecked')).toBeInTheDocument();
        expect(screen.getByText(/sftp:\/\/files\.example\.com · datasets\/all\.zip/)).toBeInTheDocument();
        expect(screen.getByText('finetune.datasetRemoteZipNoPreview')).toBeInTheDocument();
        expect(getTrainingDatasetPreview).not.toHaveBeenCalled();
    });
    it('asks for the SFTP password on every run and sends it only with the submission', async () => {
        const model: TrainingCapability = { capability_id: 'vl', model_name: 'Qwen2.5-VL-3B', input_types: ['image_text'], training_methods: ['lora'], base_model_id: 3, registered: true, validation_status: 'gpu_smoke_passed' };
        vi.mocked(listTrainingServices).mockResolvedValue([{ id: 7, server: 'Customer training' }]);
        vi.mocked(discoverTrainingModels).mockResolvedValue({ models: [model] });
        vi.mocked(listTrainingDatasets).mockResolvedValue({ data: [remoteDataset], total: 1 });
        vi.mocked(preflightTraining).mockResolvedValue({ passed: true, checks: [] });
        const rejected = new ApiError({}, { message: 'Source rejected.', envelope: { status_code: 10132, status_message: 'cannot connect to the SFTP data source (secret-value)' } });
        vi.mocked(submitTraining).mockRejectedValueOnce(rejected).mockResolvedValueOnce({ ...task, id: 'new-task' });
        const created = vi.fn();
        render(<CreateTask rtClick={vi.fn()} gpuClick={vi.fn()} onCancel={vi.fn()} onCreate={created} />);
        const user = userEvent.setup();
        await user.click(screen.getByLabelText('finetune.type_image_text'));
        await user.click(screen.getByRole('combobox', { name: 'finetune.rtService' }));
        await user.click(await screen.findByRole('option', { name: 'Customer training' }));
        await user.click(screen.getByRole('combobox', { name: 'finetune.baseModel' }));
        await user.click(await screen.findByRole('option', { name: 'Qwen2.5-VL-3B' }));
        fireEvent.change(screen.getByLabelText('finetune.finetuneModelName'), { target: { value: 'receipts-v1' } });
        await user.click(screen.getByRole('combobox', { name: 'finetune.datasetExistingVersion' }));
        await user.click(await screen.findByRole('option', { name: 'receipts · remote1' }));
        expect(screen.getByText('finetune.datasetRemoteChecked')).toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'finetune.checkAndCreate' }));
        expect(screen.getByRole('alert')).toHaveTextContent('finetune.datasetSourcePasswordRequired');
        expect(submitTraining).not.toHaveBeenCalled();
        fireEvent.change(screen.getByLabelText('finetune.datasetConnection_password_required'), { target: { value: 'secret-value' } });
        await user.click(screen.getByRole('button', { name: 'finetune.checkAndCreate' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('Source rejected. finetune.datasetErrorDetailcannot connect to the SFTP data source (••••)');
        await user.click(screen.getByRole('button', { name: 'finetune.checkAndCreate' }));
        await waitFor(() => expect(created).toHaveBeenCalledWith('new-task'));
        expect(submitTraining).toHaveBeenLastCalledWith(expect.objectContaining({ train_data: [remoteDataset], dataset_credentials: { password: 'secret-value' } }));
    });
});

describe('training method choice', () => {
    const textModel: TrainingCapability = { capability_id: 'qwen3', model_name: 'Qwen3-0.6B', input_types: ['text'], training_methods: ['lora', 'freeze', 'full'], base_model_id: 3, registered: true, validation_status: 'gpu_smoke_passed' };
    const visionModel: TrainingCapability = { ...textModel, capability_id: 'vl', model_name: 'Qwen2.5-VL-3B', input_types: ['image_text'], training_methods: ['lora', 'freeze'] };
    const textData: TrainingFile = { ...dataset, id: 'text1', version_id: 'text1', name: 'text.json', dataset_report: { ...report, data_type: 'text', samples: 8, media: 0 } };
    async function prepare(model: TrainingCapability, data: TrainingFile) {
        vi.mocked(listTrainingServices).mockResolvedValue([{ id: 7, server: 'Customer training' }]);
        vi.mocked(discoverTrainingModels).mockResolvedValue({ models: [model] });
        vi.mocked(listTrainingDatasets).mockResolvedValue({ data: [data], total: 1 });
        vi.mocked(preflightTraining).mockResolvedValue({ passed: true, checks: [] });
        vi.mocked(submitTraining).mockResolvedValue({ ...task, id: 'new-task' });
        render(<CreateTask rtClick={vi.fn()} gpuClick={vi.fn()} onCancel={vi.fn()} onCreate={vi.fn()} />);
        const user = userEvent.setup();
        if (model.input_types[0] !== 'text') await user.click(screen.getByLabelText(`finetune.type_${model.input_types[0]}`));
        await user.click(screen.getByRole('combobox', { name: 'finetune.rtService' }));
        await user.click(await screen.findByRole('option', { name: 'Customer training' }));
        await user.click(screen.getByRole('combobox', { name: 'finetune.baseModel' }));
        await user.click(await screen.findByRole('option', { name: model.model_name }));
        fireEvent.change(screen.getByLabelText('finetune.finetuneModelName'), { target: { value: 'method-v1' } });
        await user.click(screen.getByRole('combobox', { name: 'finetune.datasetExistingVersion' }));
        await user.click(await screen.findByRole('option', { name: new RegExp(`^${data.name}`) }));
        return user;
    }
    it('sends full fine-tuning with its own parameters and a smaller default learning rate', async () => {
        const user = await prepare(textModel, textData);
        expect(screen.getByLabelText('finetune.param_lora_rank')).toBeInTheDocument();
        await user.click(screen.getByLabelText('finetune.fullFineTune'));
        expect(screen.queryByLabelText('finetune.param_lora_rank')).not.toBeInTheDocument();
        expect(screen.getByText('finetune.methodHint_full')).toBeInTheDocument();
        await user.click(screen.getByRole('button', { name: 'finetune.checkAndCreate' }));
        await waitFor(() => expect(submitTraining).toHaveBeenCalled());
        const sent = vi.mocked(submitTraining).mock.calls[0][0];
        expect(sent.method).toBe('full');
        expect(sent.extra_params).toEqual(expect.objectContaining({ learning_rate: 0.00001 }));
        expect(sent.extra_params).not.toHaveProperty('lora_rank');
        expect(sent.extra_params).not.toHaveProperty('freeze_trainable_layers');
    });
    it('offers freeze but not full for an image model and sends the trainable layer count', async () => {
        const imageData: TrainingFile = { ...dataset, id: 'img1', version_id: 'img1', name: 'images.zip', dataset_report: { ...report, data_type: 'image_text' } };
        const user = await prepare(visionModel, imageData);
        expect(screen.getByLabelText('finetune.fullFineTune')).toBeDisabled();
        expect(screen.getByText('finetune.methodUnavailable')).toBeInTheDocument();
        await user.click(screen.getByLabelText('finetune.freeze'));
        fireEvent.change(screen.getByLabelText('finetune.param_freeze_trainable_layers'), { target: { value: '4' } });
        await user.click(screen.getByRole('button', { name: 'finetune.checkAndCreate' }));
        await waitFor(() => expect(submitTraining).toHaveBeenCalled());
        const sent = vi.mocked(submitTraining).mock.calls[0][0];
        expect(sent.method).toBe('freeze');
        expect(sent.extra_params).toEqual(expect.objectContaining({ freeze_trainable_layers: 4, learning_rate: 0.0001 }));
        expect(sent.extra_params).not.toHaveProperty('lora_rank');
    });
});


describe('temporary uploads remain outside the reusable dataset selector', () => {
    it('shows a temporary selection without adding a version or reloading saved datasets', async () => {
        const temporary = { ...dataset, id: 'temporary-id', upload_id: 'temporary-id', temporary: true, name: 'temporary.zip' };
        vi.mocked(uploadTrainingFile).mockResolvedValue(temporary);
        function Harness() {
            const [files, setFiles] = useState<TrainingFile[]>([]);
            return <CreateTaskList dataType="video_text" files={files} onChange={setFiles} />;
        }
        render(<Harness />);
        await waitFor(() => expect(listTrainingDatasets).toHaveBeenCalledOnce());
        fireEvent.click(screen.getByRole('button', { name: 'finetune.temporaryUpload' }));
        fireEvent.change(screen.getByLabelText('finetune.uploadDataset'), { target: { files: [new File(['data'], 'temporary.zip')] } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        await screen.findByText('finetune.temporaryDataset');
        expect(screen.getByText('temporary.zip')).toBeVisible();
        expect(listTrainingDatasets).toHaveBeenCalledOnce();
        expect(uploadCatalogDataset).not.toHaveBeenCalled();
        expect(importTrainingDataset).not.toHaveBeenCalled();
        expect(getDatasetPreview).toHaveBeenCalledWith('temporary-id', 'temporary');
    });
});
