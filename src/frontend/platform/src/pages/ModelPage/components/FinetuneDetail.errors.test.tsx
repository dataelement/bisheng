import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import FinetuneDetail from './FinetuneDetail';
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
