import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { FinetuneDetail } from './FinetuneDetail';
const updateName = vi.hoisted(() => vi.fn());

vi.mock('@/controllers/API', () => ({ getModelInfoApi: vi.fn() }));
vi.mock('@/controllers/API/finetune', () => ({
    getTaskInfoApi: vi.fn().mockResolvedValue({ finetune: {
        id: 1, model_name: 'Model', status: 3, model_id: null, create_time: '', preset_data: [], train_data: [],
    } }),
    updataTaskNameApi: updateName, cancelTaskApi: vi.fn(), publishTaskApi: vi.fn(), unPublishTaskApi: vi.fn(),
}));
vi.mock('@/controllers/API/finetuneV2', () => ({ getTrainingInfo: vi.fn().mockResolvedValue({ finetune: {id: '1', model_name: 'Model', status: 3, train_data: [], preset_data: []} }), cancelTraining: vi.fn() }));
vi.mock('./FinetuneResult', () => ({ default: () => null }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn(), handleUiRequest: vi.fn() }));
afterEach(cleanup);

it('passes a rejecting rename promise through the actual finetune page and retries the retained draft', async () => {
    updateName.mockRejectedValueOnce(new Error('Rename failed')).mockResolvedValueOnce({});
    const onStatusChange = vi.fn();
    render(<FinetuneDetail id="1" onDelete={vi.fn()} onStatusChange={onStatusChange} />);
    const name = await screen.findByText('Model');
    fireEvent.click(name.parentElement!.querySelector('button')!);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'DraftModel' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    await waitFor(() => expect(updateName).toHaveBeenCalledWith('1', 'DraftModel'));
    expect(screen.getByRole('textbox')).toHaveValue('DraftModel');
    expect(onStatusChange).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole('textbox')).toBeEnabled());
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    await screen.findByText('DraftModel');
    expect(onStatusChange).toHaveBeenCalledWith(3);
});

it('shows how the training data reached the training service', async () => {
    const { getTrainingInfo } = await import('@/controllers/API/finetuneV2');
    vi.mocked(getTrainingInfo).mockResolvedValueOnce({ finetune: { id: '2', model_name: 'Pushed', base_model_name: 'Qwen3-0.6B', status: 4, create_time: '', train_data: [], preset_data: [],
        contract_version: 2, extra_params: { contract_version: 2 }, dataset_report: { transfer: 'push' } } });
    render(<FinetuneDetail id="2" onDelete={vi.fn()} onStatusChange={vi.fn()} />);
    expect(await screen.findByText('finetune.datasetTransfer_push')).toBeInTheDocument();
});

it('lists training artifacts as files with readable sizes instead of raw JSON', async () => {
    const { getTrainingInfo } = await import('@/controllers/API/finetuneV2');
    vi.mocked(getTrainingInfo).mockResolvedValueOnce({ finetune: { id: '3', model_name: 'Done', base_model_name: 'Qwen3-0.6B', status: 4, create_time: '', train_data: [], preset_data: [],
        contract_version: 2, extra_params: { contract_version: 2 }, artifact_report: { complete: false, missing: ['tokenizer_config.json'],
            files: [{ name: 'adapter_model.safetensors', size: 20236472, sha256: 'a'.repeat(64) }] } } });
    render(<FinetuneDetail id="3" onDelete={vi.fn()} onStatusChange={vi.fn()} />);
    expect(await screen.findByText('adapter_model.safetensors')).toBeInTheDocument();
    expect(screen.getByText('19.3 MB')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('finetune.artifactsMissing');
    expect(screen.queryByText(/"sha256"/)).not.toBeInTheDocument();
});

it('uses task-provided online state without requesting FT management details', async () => {
    const { getTrainingInfo } = await import('@/controllers/API/finetuneV2');
    const { getModelInfoApi } = await import('@/controllers/API');
    const { bsConfirm } = await import('@/components/bs-ui/alertDialog/useConfirm');
    vi.mocked(getTrainingInfo).mockResolvedValueOnce({ finetune: { id: '60', model_name: 'Published', base_model_name: 'base', status: 5, create_time: '',
        train_data: [], preset_data: [], method: 'full' }, model_online: true });
    render(<FinetuneDetail id="60" onDelete={vi.fn()} onStatusChange={vi.fn()} />);
    await screen.findByText('Published');
    fireEvent.click(screen.getByRole('button', { name: 'bs:delete' }));
    expect(bsConfirm).toHaveBeenCalledWith(expect.objectContaining({ desc: 'finetune.confirmDeleteOnlineModel' }));
    expect(getModelInfoApi).not.toHaveBeenCalled();
});

