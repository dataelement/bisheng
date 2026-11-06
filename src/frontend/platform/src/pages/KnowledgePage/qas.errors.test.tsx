import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import QasPage from './qas';

const mock = vi.hoisted(() => ({ update: vi.fn(), report: vi.fn(), notice: vi.fn(), refresh: vi.fn(), reload: vi.fn() }));
vi.mock('@/controllers/API', () => ({ updateQaStatus: mock.update, deleteQa: vi.fn(), getQaFile: vi.fn(), getQaList: vi.fn() }));
vi.mock('@/controllers/API/permission', () => ({ checkResourceActionApi: vi.fn().mockResolvedValue({ allowed: true }) }));
vi.mock('@/controllers/request', () => ({ showApiError: mock.report }));
vi.mock('@bisheng/ui', async (original) => ({ ...await original<typeof import('@bisheng/ui')>(), notification: { open: mock.notice } }));
vi.mock('react-router-dom', async (original) => ({ ...await original<typeof import('react-router-dom')>(), useParams: () => ({ id: '1' }) }));
vi.mock('./components/EditQa', () => ({ EditQa: () => null }));
vi.mock('./components/ImportQa', () => ({ ImportQa: () => null }));
vi.mock('@/util/hook', () => ({ useTable: () => ({
    page: 1, pageSize: 10, total: 1, loading: false, setPage: vi.fn(), search: vi.fn(),
    data: [{ id: 1, question: 'Question', answer: 'Answer', status: 0, source: 1, update_time: '2026-10-22T00:00:00' }],
    reload: mock.reload, refreshData: mock.refresh,
}) }));
beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

it('keeps the QA failure rollback and delegates the original request error once', async () => {
    const error = new Error('Update failed');
    mock.update.mockRejectedValueOnce(error);
    render(<MemoryRouter><QasPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('switch'));
    await waitFor(() => expect(mock.report).toHaveBeenCalledWith(error));
    expect(mock.refresh).toHaveBeenLastCalledWith(expect.any(Function), { status: 3 });
    expect(mock.notice).not.toHaveBeenCalled();
});

it('retains the named batch partial-failure summary', async () => {
    mock.update.mockRejectedValueOnce(new Error('Item failed'));
    render(<MemoryRouter><QasPage /></MemoryRouter>);
    await screen.findByRole('switch');
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    fireEvent.click(await screen.findByRole('button', { name: 'enable' }));
    await waitFor(() => expect(mock.notice).toHaveBeenCalledWith({ type: 'warning', description: 'someItemsFailedToEnable' }));
    expect(mock.reload).toHaveBeenCalled();
});
