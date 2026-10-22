import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { getKnowledgeDetailApi } from '@/controllers/API';
import { getLlmDefaultModel } from '@/controllers/API/finetune';
import { createWorkflowApi } from '@/controllers/API/workflow';
import { showApiError } from '@/controllers/request';
import FileUploadStep4 from './FileUploadStep4';

vi.mock('@/controllers/API', () => ({ getKnowledgeDetailApi: vi.fn(), readFileByLibDatabase: vi.fn() }));
vi.mock('@/controllers/API/finetune', () => ({ getLlmDefaultModel: vi.fn().mockResolvedValue({ model_id: 1 }) }));
vi.mock('@/controllers/API/workflow', () => ({ createWorkflowApi: vi.fn().mockResolvedValue({ id: 'flow' }), getWorkflowNodeTemplate: vi.fn().mockResolvedValue([]) }));
vi.mock('@/util/flowUtils', () => ({ initNode: vi.fn() }));
vi.mock('@/controllers/request', async (importOriginal) => ({
    ...await importOriginal<typeof import('@/controllers/request')>(), showApiError: vi.fn(),
    handleUiRequest: (handler: () => Promise<void>) => () => void handler().catch(showApiError),
}));
vi.mock('@/components/bs-comp/cardComponent', () => ({ default: ({ onClick }: { onClick: () => void }) => <button onClick={onClick}>Create</button> }));
vi.mock('@/components/bs-comp/knowledgeUploadComponent/ProgressItem', () => ({ default: () => null }));
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
