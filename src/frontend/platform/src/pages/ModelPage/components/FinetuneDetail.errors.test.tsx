import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import FinetuneDetail from './FinetuneDetail';
import { getTaskInfoApi } from '@/controllers/API/finetune';
import { getModelInfoApi } from '@/controllers/API';
import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm';
const updateName = vi.hoisted(() => vi.fn());

vi.mock('@/controllers/API', () => ({ getModelInfoApi: vi.fn() }));
vi.mock('@/controllers/API/finetune', () => ({
    getTaskInfoApi: vi.fn().mockResolvedValue({ finetune: {
        id: 1, model_name: 'Model', status: 3, model_id: null, create_time: '', preset_data: [], train_data: [],
    } }),
    updataTaskNameApi: updateName, cancelTaskApi: vi.fn(), publishTaskApi: vi.fn(), unPublishTaskApi: vi.fn(),
}));
vi.mock('./FinetuneResult', () => ({ default: () => null }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn(), handleUiRequest: vi.fn() }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }));
afterEach(cleanup);

it('passes a rejecting rename promise through the actual finetune page and retries the retained draft', async () => {
    updateName.mockRejectedValueOnce(new Error('Rename failed')).mockResolvedValueOnce({});
    const onStatusChange = vi.fn();
    render(<FinetuneDetail id={1} onDelete={vi.fn()} onStatusChange={onStatusChange} />);
    const name = await screen.findByText('Model');
    fireEvent.click(name.parentElement!.querySelector('button')!);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'DraftModel' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    await waitFor(() => expect(updateName).toHaveBeenCalledWith(1, 'DraftModel'));
    expect(screen.getByRole('textbox')).toHaveValue('DraftModel');
    expect(onStatusChange).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole('textbox')).toBeEnabled());
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    await screen.findByText('DraftModel');
    expect(onStatusChange).toHaveBeenCalledWith(3);
});


it('uses task-provided online state without requesting FT management details', async () => {
    vi.mocked(getTaskInfoApi).mockResolvedValueOnce({ finetune: {
        id: 'job-60', model_name: 'Published', status: 5, model_id: 60, create_time: '', preset_data: [], train_data: [],
        server: 60, base_model: 60, base_model_name: 'base', extra_params: { gpus: 0, val_radio: 0.1, learning_rate: 0.00005 },
        reason: '', report: null, user_name: 'Operator', update_time: '', method: 'full', log_path: '', user_id: 849,
    }, model_online: true, log: null, report: null, loss_data: [] });
    render(<FinetuneDetail id="job-60" onDelete={vi.fn()} onStatusChange={vi.fn()} />);
    await screen.findByText('Published');
    fireEvent.click(screen.getByRole('button', { name: 'bs:delete' }));
    expect(bsConfirm).toHaveBeenCalledWith(expect.objectContaining({ desc: 'finetune.confirmDeleteOnlineModel' }));
    expect(getModelInfoApi).not.toHaveBeenCalled();
});
