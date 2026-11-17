import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import JSZip from 'jszip';
import { readDatasetPreview } from './DatasetPreview';
import userEvent from '@testing-library/user-event';
import { CreateTask } from './CreateTask';
import { FinetuneValidation } from './FinetuneValidation';
import { CreateTaskList } from './CreateTaskList';
import { DatasetImportDialog, safeDatasetImportError, validDatasetEndpoint } from './DatasetImportDialog';
import { getTrainingDatasetPreview, getTrainingDatasetMedia, importTrainingDataset, listTrainingDatasets } from '@/controllers/API/finetuneDatasets';
import { compatibleTrainingFiles, selectableTrainingModels, validTrainingParameters } from './finetuneHelpers';
import type { TrainingCapability, TrainingFile, TrainingTask } from '@/controllers/API/finetuneV2';
import { discoverTrainingModels, listTrainingServices, preflightTraining, submitTraining, runTrainingInference, uploadTrainingFile, uploadValidationMedia } from '@/controllers/API/finetuneV2';

vi.mock('@/controllers/API/finetuneV2', () => ({ listTrainingServices: vi.fn(), discoverTrainingModels: vi.fn(), preflightTraining: vi.fn(), submitTraining: vi.fn(), runTrainingInference: vi.fn(), uploadValidationMedia: vi.fn(), uploadTrainingFile: vi.fn() }));
vi.mock('@/controllers/API/finetuneDatasets', () => ({ listTrainingDatasets: vi.fn(), importTrainingDataset: vi.fn(), getTrainingDatasetPreview: vi.fn(), getTrainingDatasetMedia: vi.fn() }));
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise.catch(() => undefined) }));
const report = { data_type: 'video_text' as const, samples: 6, media: 6, sha256: 'abc', validated: true };
const dataset: TrainingFile = { id: 'data1', url: 'object/key', name: 'video.zip', num: 6, dataset_report: report };
const task: TrainingTask = { id: 'task1', model_name: 'video-v1', base_model_name: 'Qwen2.5-VL-3B-Instruct', status: 4, contract_version: 2, data_type: 'video_text', create_time: '' };

beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listTrainingDatasets).mockResolvedValue({ data: [], total: 0 });
    vi.mocked(getTrainingDatasetPreview).mockResolvedValue({ samples: [] });
    URL.createObjectURL = vi.fn(() => 'blob:preview'); URL.revokeObjectURL = vi.fn();
});
describe('training capability and dataset boundaries', () => {
    it('only enables registered, ready, validated models matching the modality and method', () => {
        const valid: TrainingCapability = { capability_id: 'vl', model_name: 'VL', input_types: ['video_text'], training_methods: ['lora'], base_model_id: 1, registered: true, validation_status: 'gpu_smoke_passed' };
        expect(selectableTrainingModels([valid, { ...valid, capability_id: '' }, { ...valid, model_ready: false }, { ...valid, ready: false }, { ...valid, validation_status: 'unverified' }, { ...valid, base_model_id: undefined }, { ...valid, training_methods: ['full'] }], 'video_text')).toEqual([valid]);
        expect(selectableTrainingModels([valid], 'text')).toEqual([]);
        expect(compatibleTrainingFiles([dataset], 'text')).toEqual([]);
    });
    it('uses the authoritative upload sample count and report', async () => {
        vi.mocked(uploadTrainingFile).mockResolvedValue(dataset);
        const changed = vi.fn(); render(<CreateTaskList dataType="video_text" files={[]} onChange={changed} />);
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImport' }));
        fireEvent.change(screen.getByLabelText('finetune.uploadDataset'), { target: { files: [new File(['data'], 'video.zip')] } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        await waitFor(() => expect(changed).toHaveBeenCalledWith([dataset]));
    });
    it('does not accept an image dataset for a video task', async () => {
        vi.mocked(uploadTrainingFile).mockResolvedValue({ ...dataset, dataset_report: { ...report, data_type: 'image_text' } });
        const changed = vi.fn(); render(<CreateTaskList dataType="video_text" files={[]} onChange={changed} />);
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImport' }));
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
    it('discovers the service model, preserves the real dataset count, and preflights before submission', async () => {
        const model: TrainingCapability = { capability_id: 'qwen3', model_name: 'Qwen3-0.6B', input_types: ['text'], training_methods: ['lora'], base_model_id: 3, registered: true, validation_status: 'gpu_smoke_passed' };
        vi.mocked(listTrainingServices).mockResolvedValue([{ id: 7, server: 'Customer training', sft_endpoint: 'http://training:8000' }]);
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
        fireEvent.change(screen.getByLabelText('finetune.finetuneModelName'), { target: { value: 'support-v1' } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImport' }));
        fireEvent.change(screen.getByLabelText('finetune.uploadDataset'), { target: { files: [new File(['data'], 'text.zip')] } });
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));
        await screen.findByText('text.zip');
        fireEvent.change(screen.getByLabelText('finetune.param_max_steps'), { target: { value: '-1' } });
        await user.click(screen.getByRole('button', { name: 'finetune.checkAndCreate' }));
        await waitFor(() => expect(created).toHaveBeenCalledWith('new-task'));
        expect(submitTraining).toHaveBeenCalledWith(expect.objectContaining({ server: 7, base_model: 3, capability_id: 'qwen3', data_type: 'text', train_data: [textData], extra_params: expect.objectContaining({ max_steps: -1, cutoff_len: 1024 }) }));
        expect(vi.mocked(preflightTraining).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(submitTraining).mock.invocationCallOrder[0]);
    });
});


describe('uploaded dataset preview', () => {
    it('previews UTF-8 BOM JSONL manifests inside accepted ZIP packages', async () => {
        const archive = new JSZip();
        archive.file('train.jsonl', '\uFEFF' + JSON.stringify({ instruction: 'Question', output: 'Answer' }) + '\n');
        const bytes = await archive.generateAsync({ type: 'arraybuffer' });
        const file = new File([], 'text.zip'); Object.defineProperty(file, 'arrayBuffer', { value: async () => bytes });
        const rows = await readDatasetPreview(file, 'text');
        expect(rows).toEqual([{ messages: [{ role: 'user', content: 'Question' }, { role: 'assistant', content: 'Answer' }], media: [] }]);
    });
    it('shows only the first three conversations and resolves the exact video references', async () => {
        const archive = new JSZip();
        archive.file('train.json', JSON.stringify(Array.from({ length: 4 }, (_, index) => ({ messages: [{ role: 'user', content: `<video>Question ${index}` }, { role: 'assistant', content: 'right' }], videos: ['videos/clip.mp4'] }))));
        archive.file('videos/clip.mp4', new Uint8Array([1, 2, 3]));
        const bytes = await archive.generateAsync({ type: 'arraybuffer' });
        const file = new File([], 'video.zip');
        Object.defineProperty(file, 'arrayBuffer', { value: async () => bytes });
        const rows = await readDatasetPreview(file, 'video_text');
        expect(rows).toHaveLength(3);
        expect(rows[0].messages[0].content).toBe('<video>Question 0');
        expect(rows[0].media).toEqual(['blob:preview']);
        expect(URL.createObjectURL).toHaveBeenCalledTimes(3);
    });
});


describe('single-package and epoch mode contract', () => {
    it('replaces an existing dataset when a new package is uploaded', async () => {
        vi.mocked(uploadTrainingFile).mockResolvedValue(dataset);
        const old = { ...dataset, id: 'old', dataset_report: { ...report, sha256: 'old' } };
        const changed = vi.fn();
        render(<CreateTaskList dataType="video_text" files={[old]} onChange={changed} />);
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImport' }));
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
        await waitFor(() => expect(imported).toHaveBeenCalledWith(dataset, undefined));
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
    it('rejects endpoint credentials, paths and query strings and never serializes raw errors', () => {
        expect(validDatasetEndpoint('ftp://files.example.com:21', 'ftp')).toBe(true);
        expect(validDatasetEndpoint('ftps://files.example.com', 'ftp')).toBe(true);
        expect(validDatasetEndpoint('https://objects.example.com:9000', 's3')).toBe(true);
        for (const endpoint of ['ftp://user:password@files.example.com', 'ftp://files.example.com/path', 'ftp://files.example.com?password=secret', 'https://files.example.com']) expect(validDatasetEndpoint(endpoint, 'ftp')).toBe(false);
        expect(safeDatasetImportError({ config: { password: 'secret' } }, { endpoint: '' }, 'Import failed')).toBe('Import failed');
    });
    it('shows list failures and retries without inventing a dataset', async () => {
        vi.mocked(listTrainingDatasets).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: [], total: 0 });
        render(<CreateTaskList dataType="text" files={[]} onChange={vi.fn()} />);
        expect(await screen.findByRole('alert')).toHaveTextContent('finetune.datasetListFailed');
        fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetRefresh' }));
        await screen.findByText('finetune.datasetEmpty');
    });
});
