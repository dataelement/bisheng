import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createPlatformQueryClient } from '@/queryClient';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DatasetImportDialog } from './DatasetImportDialog';
import type { TrainingDataType } from '@/controllers/API/finetuneV2';

const mock = vi.hoisted(() => ({ qa: vi.fn(), local: vi.fn(), read: vi.fn(), error: vi.fn() }));
vi.mock('@/controllers/API', () => ({ readFileLibDatabase: mock.read }));
vi.mock('@/controllers/API/finetuneDatasets', () => ({ importQADataset: mock.qa, uploadCatalogDataset: mock.local, importTrainingDataset: vi.fn() }));
vi.mock('@/hooks/useKnowledgePageScope', () => ({ useKnowledgePageScope: () => ({ scopes: { ordinary: { identityKey: 'user:7', tenantId: 60, managementTenantId: 60, view: 'ordinary' } } }) }));
vi.mock('@/controllers/managementScope', () => ({ managementRequestScope: () => 60 }));
vi.mock('@/controllers/request', () => ({ showApiError: mock.error }));
const file = { id: 'text', name: 'text', url: 'text.json', num: 1, dataset_report: { data_type: 'text', validated: true, samples: 1, media: 0, sha256: 'hash' } };

afterEach(cleanup);
beforeEach(() => {
    vi.clearAllMocks();
    mock.qa.mockResolvedValue(file);
    mock.local.mockResolvedValue(file);
    mock.read.mockReset().mockResolvedValue({ data: [{ id: '101', name: 'QA library' }], next_cursor: null });
});
function setup(dataType: TrainingDataType = 'text', chooseType = false) {
    const imported = vi.fn();
    function Harness() {
        const [open, setOpen] = useState(true);
        return <><button onClick={() => setOpen(true)}>Open import</button>{open && <DatasetImportDialog dataType={dataType} onDataTypeChange={chooseType ? vi.fn() : undefined} onClose={() => setOpen(false)} onImported={imported} />}</>;
    }
    render(<QueryClientProvider client={createPlatformQueryClient()}><Harness /></QueryClientProvider>);
    return { imported };
}
function selectQA() {
    fireEvent.click(screen.getByRole('radio', { name: 'finetune.datasetSource_qa' }));
}
const qaSelect = () => screen.getByRole('combobox', { name: 'finetune.datasetQaKnowledge' });
const submit = () => fireEvent.click(screen.getByRole('button', { name: 'finetune.datasetImportAndCheck' }));

it('imports local messages data through the single dialog', async () => {
    const { imported } = setup();
    fireEvent.change(screen.getByLabelText('finetune.datasetImportName'), { target: { value: 'Dataset' } });
    const upload = new File(['[]'], 'text.json');
    fireEvent.change(screen.getByLabelText('finetune.uploadDataset'), { target: { files: [upload] } });
    submit();
    await waitFor(() => expect(mock.local).toHaveBeenCalledWith(upload, 'text', 'Dataset', expect.any(Function)));
    await waitFor(() => expect(imported).toHaveBeenCalledOnce());
    expect(mock.qa).not.toHaveBeenCalled();
});
it('switches from local data to QA and submits only selected library IDs', async () => {
    setup();
    fireEvent.change(screen.getByLabelText('finetune.datasetImportName'), { target: { value: 'QA dataset' } });
    fireEvent.change(screen.getByLabelText('finetune.uploadDataset'), { target: { files: [new File(['[]'], 'old.json')] } });
    selectQA();
    expect(screen.queryByLabelText('finetune.uploadDataset')).not.toBeInTheDocument();
    submit();
    expect(mock.qa).not.toHaveBeenCalled();
    fireEvent.click(qaSelect());
    fireEvent.click(await screen.findByRole('option', { name: 'QA library' }));
    fireEvent.keyDown(qaSelect(), { key: 'Escape' });
    submit();
    await waitFor(() => expect(mock.qa).toHaveBeenCalledWith('QA dataset', [101]));
    expect(mock.local).not.toHaveBeenCalled();
});
it('keeps QA imports text-only and does not offer legacy in the category selector', async () => {
    setup('video_text', true);
    fireEvent.click(screen.getByRole('combobox', { name: 'finetune.datasetCategory' }));
    expect(await screen.findByRole('option', { name: 'finetune.type_text' })).toBeVisible();
    expect(screen.queryByRole('option', { name: 'finetune.type_legacy' })).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'finetune.datasetCategory' }), { key: 'Escape' });
    selectQA();
    expect(screen.getByRole('combobox', { name: 'finetune.datasetCategory' })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByRole('combobox', { name: 'finetune.datasetCategory' })).toHaveTextContent('finetune.type_text');
});
it('loads more QA pages and retains selections while searching', async () => {
    mock.read.mockResolvedValueOnce({ data: [{ id: '101', name: 'First QA' }], next_cursor: 'page-2' })
        .mockResolvedValueOnce({ data: [{ id: '102', name: 'Second QA' }], next_cursor: null })
        .mockResolvedValueOnce({ data: [{ id: '103', name: 'Search QA' }], next_cursor: null });
    setup();
    fireEvent.change(screen.getByLabelText('finetune.datasetImportName'), { target: { value: 'QA dataset' } });
    selectQA();
    fireEvent.click(qaSelect());
    fireEvent.click(await screen.findByRole('option', { name: 'First QA' }));
    fireEvent.scroll(screen.getByRole('listbox').parentElement!);
    fireEvent.click(await screen.findByRole('option', { name: 'Second QA' }));
    expect(mock.read).toHaveBeenNthCalledWith(2, { cursor: 'page-2', pageSize: 60, name: '', type: 1, action: 'visible' });
    fireEvent.change(qaSelect(), { target: { value: 'Search' } });
    fireEvent.click(await screen.findByRole('option', { name: 'Search QA' }));
    fireEvent.keyDown(qaSelect(), { key: 'Escape' });
    submit();
    await waitFor(() => expect(mock.qa).toHaveBeenCalledWith('QA dataset', [101, 102, 103]));
});
it('ignores a stale QA search response', async () => {
    let resolveOld!: (value: { data: { id: string; name: string }[]; next_cursor: null }) => void;
    mock.read.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }))
        .mockResolvedValueOnce({ data: [{ id: '104', name: 'Current result' }], next_cursor: null });
    setup(); selectQA(); fireEvent.click(qaSelect());
    fireEvent.change(qaSelect(), { target: { value: 'Current' } });
    await screen.findByRole('option', { name: 'Current result' });
    await act(async () => resolveOld({ data: [{ id: '105', name: 'Stale result' }], next_cursor: null }));
    expect(screen.getByRole('option', { name: 'Current result' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Stale result' })).not.toBeInTheDocument();
});
it('reports a QA load error and allows retry by reopening', async () => {
    const error = new Error('QA unavailable'); mock.read.mockRejectedValueOnce(error);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
        setup(); selectQA(); fireEvent.click(qaSelect());
        await waitFor(() => expect(mock.error).toHaveBeenCalledWith(error));
        fireEvent.keyDown(qaSelect(), { key: 'Escape' }); fireEvent.click(qaSelect());
        expect(await screen.findByRole('option', { name: 'QA library' })).toBeInTheDocument();
    } finally { consoleError.mockRestore(); }
});
it('resets the source and draft after closing and reopening', () => {
    setup(); selectQA();
    fireEvent.click(screen.getByRole('button', { name: 'bs:cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open import' }));
    expect(screen.getByRole('radio', { name: 'finetune.datasetSource_local' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByLabelText('finetune.datasetImportName')).toHaveValue('');
});
it('retains a failed QA draft and allows retry', async () => {
    mock.qa.mockRejectedValueOnce(new Error('Create failed'));
    const { imported } = setup(); selectQA();
    fireEvent.change(screen.getByLabelText('finetune.datasetImportName'), { target: { value: 'Retry dataset' } });
    fireEvent.click(qaSelect()); fireEvent.click(await screen.findByRole('option', { name: 'QA library' }));
    fireEvent.keyDown(qaSelect(), { key: 'Escape' }); submit();
    await waitFor(() => expect(mock.qa).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText('finetune.datasetImportName')).toHaveValue('Retry dataset');
    expect(imported).not.toHaveBeenCalled(); submit();
    await waitFor(() => expect(imported).toHaveBeenCalledOnce());
});
