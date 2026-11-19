import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import CreateTask from './CreateTask';
import { getTrainingServicesApi } from '@/controllers/API/finetune';

vi.mock('@/controllers/API', () => ({ getFTServicesApi: vi.fn() }));
vi.mock('@/controllers/API/finetune', () => ({
    createTaskApi: vi.fn(),
    getTrainingServicesApi: vi.fn().mockResolvedValue([{ id: 60, server: 'FT service' }]),
}));
vi.mock('./CreateTaskList', () => ({ default: () => null }));
afterEach(cleanup);

it('loads the task service picker and hides FT management from an ordinary menu user', async () => {
    render(<CreateTask rtClick={undefined} gpuClick={vi.fn()} onCancel={vi.fn()} onCreate={vi.fn()} />);
    await waitFor(() => expect(getTrainingServicesApi).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: 'finetune.rtServiceManagement' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'bs:create' })).toBeEnabled();
});

it('retains FT management for an administrator', async () => {
    render(<CreateTask rtClick={vi.fn()} gpuClick={vi.fn()} onCancel={vi.fn()} onCreate={vi.fn()} />);
    await waitFor(() => expect(getTrainingServicesApi).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: 'finetune.rtServiceManagement' })).toBeEnabled();
});
