import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { getKnowledgeDetailApi, readFileByLibDatabase } from '@/controllers/API';
import { getLlmDefaultModel } from '@/controllers/API/finetune';
import { createWorkflowApi } from '@/controllers/API/workflow';
import { showApiError } from '@/controllers/request';
import FileUploadStep4 from './FileUploadStep4';

const notices = vi.hoisted(() => vi.fn());
const captureRow = vi.hoisted(() => vi.fn());
const stableTranslation = vi.hoisted(() => (key: string) => key);
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: stableTranslation }) }));
vi.mock('@bisheng/ui', async (load) => ({ ...await load<typeof import('@bisheng/ui')>(), toast: { show: notices } }));
vi.mock('@/controllers/API', () => ({ getKnowledgeDetailApi: vi.fn(), readFileByLibDatabase: vi.fn() }));
vi.mock('@/controllers/API/finetune', () => ({ getLlmDefaultModel: vi.fn().mockResolvedValue({ model_id: 1 }) }));
vi.mock('@/controllers/API/workflow', () => ({ createWorkflowApi: vi.fn().mockResolvedValue({ id: 'flow' }), getWorkflowNodeTemplate: vi.fn().mockResolvedValue([]) }));
vi.mock('@/util/flowUtils', () => ({ initNode: vi.fn() }));
vi.mock('@/controllers/request', async (importOriginal) => ({
    ...await importOriginal<typeof import('@/controllers/request')>(), showApiError: vi.fn(),
    handleUiRequest: (handler: () => Promise<void>) => () => void handler().catch(showApiError),
}));
vi.mock('@/components/bs-comp/cardComponent', () => ({ default: ({ onClick }: { onClick: () => void }) => <button onClick={onClick}>Create</button> }));
vi.mock('@/components/bs-comp/knowledgeUploadComponent/ProgressItem', () => ({ default: ({ item }: { item: unknown }) => { captureRow(item); return null; } }));
afterEach(cleanup);

it('does not load models or create a workflow after knowledge details fail', async () => {
    const error = new Error('Details unavailable');
    vi.mocked(getKnowledgeDetailApi).mockRejectedValue(error);
    render(<MemoryRouter><FileUploadStep4 data={[]} kId="1" hasRepeat={false} /></MemoryRouter>);
    await waitFor(() => expect(getKnowledgeDetailApi).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(error));
    expect(getLlmDefaultModel).not.toHaveBeenCalled();
    expect(createWorkflowApi).not.toHaveBeenCalled();
});

it('uses a local parse fallback and only notifies once when a failed file is polled again', async () => {
    notices.mockClear();
    vi.mocked(getKnowledgeDetailApi).mockResolvedValue({} as never);
    vi.mocked(readFileByLibDatabase).mockResolvedValue({ data: [{ file_name: 'a.txt', status: 3, remark: 'PRIVATE stack' }] } as never);
    const files = [{ id: 'one', fileId: 'one', fileName: 'a.txt' }];
    const page = render(<MemoryRouter><FileUploadStep4 data={files} kId="1" hasRepeat={false} /></MemoryRouter>);
    await waitFor(() => expect(notices).toHaveBeenCalledWith({ type: 'error', message: 'parseFailed' }));
    const calls = vi.mocked(readFileByLibDatabase).mock.calls.length;
    page.rerender(<MemoryRouter><FileUploadStep4 data={[...files]} kId="1" hasRepeat={false} /></MemoryRouter>);
    await waitFor(() => expect(vi.mocked(readFileByLibDatabase).mock.calls.length).toBeGreaterThan(calls));
    expect(notices).toHaveBeenCalledTimes(1);
    expect(captureRow).toHaveBeenCalledWith(expect.objectContaining({ reason: 'parseFailed', failureEvidence: expect.objectContaining({ remark: 'PRIVATE stack' }) }));
});
