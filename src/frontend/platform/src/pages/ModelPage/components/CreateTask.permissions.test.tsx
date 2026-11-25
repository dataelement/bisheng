import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CreateTask } from './CreateTask';
import { listTrainingServices } from '@/controllers/API/finetuneV2';

vi.mock('@/controllers/API/finetuneV2', () => ({
    listTrainingServices: vi.fn().mockResolvedValue([{ id: 60, server: 'FT service' }]),
    discoverTrainingModels: vi.fn(), preflightTraining: vi.fn(), submitTraining: vi.fn(),
}));
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise.catch(() => undefined) }));
vi.mock('./CreateTaskList', () => ({ CreateTaskList: () => null }));
afterEach(cleanup);

it('loads the task service picker and hides FT management from an ordinary menu user', async () => {
    render(<CreateTask rtClick={undefined} gpuClick={vi.fn()} onCancel={vi.fn()} onCreate={vi.fn()} />);
    await waitFor(() => expect(listTrainingServices).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: 'finetune.rtServiceManagement' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'finetune.checkAndCreate' })).toBeEnabled();
});

it('retains FT management for an administrator', async () => {
    render(<CreateTask rtClick={vi.fn()} gpuClick={vi.fn()} onCancel={vi.fn()} onCreate={vi.fn()} />);
    await waitFor(() => expect(listTrainingServices).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: 'finetune.rtServiceManagement' })).toBeEnabled();
});
