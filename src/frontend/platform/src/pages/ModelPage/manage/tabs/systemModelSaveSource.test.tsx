import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import AssisModel from './AssisModel';
import EvaluationModel from './EvaluationModel';
import { KnowledgeModel } from './KnowledgeModel';
import WorkflowModel from './WorkflowModel';

const mocks = vi.hoisted(() => ({
    knowledge: vi.fn(), saveKnowledge: vi.fn(), assistant: vi.fn(), saveAssistant: vi.fn(),
    evaluation: vi.fn(), saveEvaluation: vi.fn(), workflow: vi.fn(), saveWorkflow: vi.fn(),
    notice: vi.fn(), toast: vi.fn(), t: (key: string) => key,
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('@/controllers/API/finetune', () => ({
    getKnowledgeModelEnvelope: mocks.knowledge, updateKnowledgeModelConfig: mocks.saveKnowledge,
    getAssistantModelEnvelope: mocks.assistant, updateAssistantModelConfig: mocks.saveAssistant,
    getEvaluationModelEnvelope: mocks.evaluation, updateEvaluationModelConfig: mocks.saveEvaluation,
    getLlmDefaultModelEnvelope: mocks.workflow, setLlmDefaultModel: mocks.saveWorkflow,
}));
vi.mock('@/controllers/request', () => ({ showApiError: mocks.notice }));
vi.mock('./WorkbenchModel', () => ({ defalutPrompt: 'default prompt' }));
vi.mock('../ModelFieldHint', () => ({ ModelFieldHint: () => null }));
interface PickerNode { value: string; label: string; disabled?: boolean; children?: PickerNode[] }
interface PickerProps {
    value: string[] | null;
    options: PickerNode[];
    allowClear?: boolean;
    onChange: (path: string[] | null) => void;
    'aria-label': string;
}
vi.mock('@bisheng/ui', async (original) => ({
    ...await original<typeof import('@bisheng/ui')>(),
    toast: { show: mocks.toast },
    Cascader: ({ value, options, allowClear, onChange, 'aria-label': label }: PickerProps) => <select
        aria-label={label} value={value?.at(-1) ?? ''}
        onChange={event => onChange(event.target.value ? ['provider', event.target.value] : null)}>
        {allowClear && <option value="">Clear</option>}
        {options.flatMap(group => (group.children ?? []).map(model => <option key={`${group.value}:${model.value}`} value={model.value} disabled={model.disabled}>{model.label}</option>))}
    </select>,
}));
const options = [{ value: 'provider', label: 'Provider', children: [{ value: '1', label: 'Embedding' }, { value: '7', label: 'Replacement' }, { value: '9', label: 'Original' }] }];
const inference = { model_id: '9', agent_executor_type: 'function call', knowledge_max_content: 15000, knowledge_sort_index: false, default: true, streaming: false };
const knowledge = { embedding_model_id: '1', extract_title_model_id: '9', qa_similar_model_id: '9', asr_model_id: null, abstract_enabled: true, auto_tag_enabled: true, abstract_prompt: 'summary', auto_tag_prompt: 'tags' };
const cases = [
    { name: 'knowledge', load: mocks.knowledge, save: mocks.saveKnowledge, initial: knowledge, local: { ...knowledge, extract_title_model_id: '7' }, field: 'model.documentSummaryModel', render: () => <KnowledgeModel llmOptions={options} embeddings={options} onBack={vi.fn()} /> },
    { name: 'assistant', load: mocks.assistant, save: mocks.saveAssistant, initial: { llm_list: [inference], auto_llm: inference }, local: { llm_list: [{ ...inference, model_id: '7' }], auto_llm: inference }, field: 'build.selectModel', render: () => <AssisModel llmOptions={options} onBack={vi.fn()} /> },
    { name: 'evaluation', load: mocks.evaluation, save: mocks.saveEvaluation, initial: { model_id: '9' }, local: { model_id: '7' }, field: 'build.selectModel', render: () => <EvaluationModel llmOptions={options} onBack={vi.fn()} /> },
    { name: 'workflow', load: mocks.workflow, save: mocks.saveWorkflow, initial: { model_id: '9' }, local: { model_id: '7' }, field: 'build.selectModel', render: () => <WorkflowModel llmOptions={options} onBack={vi.fn()} /> },
];
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it.each(cases)('$name keeps saved provenance during edits, then reloads local provenance and diagnostics after saving', async spec => {
    spec.load.mockResolvedValueOnce({ data: spec.initial, inherited_from_root: true }).mockResolvedValue({ data: spec.local, inherited_from_root: false });
    spec.save.mockResolvedValue(undefined);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    render(<QueryClientProvider client={client}>{spec.render()}</QueryClientProvider>);
    const save = await screen.findByRole('button', { name: 'model.saveLocalConfiguration' });
    const picker = screen.getAllByRole('combobox', { name: spec.field })[0];
    fireEvent.change(picker, { target: { value: '7' } });
    expect(screen.getByText('model.systemConfigInheritedBadge')).toBeInTheDocument();
    expect(screen.getByText('model.draftSourceHelp')).toBeInTheDocument();
    fireEvent.click(save);
    await waitFor(() => expect(spec.save).toHaveBeenCalledOnce());
    await waitFor(() => expect(spec.load).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('model.systemConfigInheritedBadge')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'model.save' })).toBeEnabled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['system-model-settings'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['system-model-settings-impact'] });
    client.clear();
});

it.each(cases)('$name preserves its draft and inherited source when saving fails', async spec => {
    spec.load.mockResolvedValue({ data: spec.initial, inherited_from_root: true });
    spec.save.mockRejectedValue(new Error('write refused'));
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    render(<QueryClientProvider client={client}>{spec.render()}</QueryClientProvider>);
    const save = await screen.findByRole('button', { name: 'model.saveLocalConfiguration' });
    fireEvent.change(screen.getAllByRole('combobox', { name: spec.field })[0], { target: { value: '7' } });
    fireEvent.click(save);
    await waitFor(() => expect(mocks.notice).toHaveBeenCalledOnce());
    expect(screen.getAllByRole('combobox', { name: spec.field })[0]).toHaveValue('7');
    expect(screen.getByText('model.systemConfigInheritedBadge')).toBeInTheDocument();
    expect(spec.load).toHaveBeenCalledOnce();
    expect(invalidate).not.toHaveBeenCalled();
    expect(save).toBeEnabled();
    client.clear();
});

it("saving one column preserves another column's unsaved draft and saved source", async () => {
    mocks.evaluation.mockResolvedValueOnce({ data: { model_id: '9' }, inherited_from_root: true })
        .mockResolvedValue({ data: { model_id: '7' }, inherited_from_root: false });
    mocks.workflow.mockResolvedValue({ data: { model_id: '9' }, inherited_from_root: true });
    mocks.saveEvaluation.mockResolvedValue(undefined);
    const client = new QueryClient();
    render(<QueryClientProvider client={client}>
        <section data-testid="evaluation"><EvaluationModel llmOptions={options} onBack={vi.fn()} /></section>
        <section data-testid="workflow"><WorkflowModel llmOptions={options} onBack={vi.fn()} /></section>
    </QueryClientProvider>);
    const evaluation = within(screen.getByTestId('evaluation'));
    const workflow = within(screen.getByTestId('workflow'));
    await evaluation.findByRole('button', { name: 'model.saveLocalConfiguration' });
    await workflow.findByRole('button', { name: 'model.saveLocalConfiguration' });
    fireEvent.change(evaluation.getByRole('combobox'), { target: { value: '7' } });
    fireEvent.change(workflow.getByRole('combobox'), { target: { value: '7' } });
    fireEvent.click(evaluation.getByRole('button', { name: 'model.saveLocalConfiguration' }));
    await waitFor(() => expect(evaluation.queryByText('model.systemConfigInheritedBadge')).not.toBeInTheDocument());
    expect(workflow.getByRole('combobox')).toHaveValue('7');
    expect(workflow.getByText('model.systemConfigInheritedBadge')).toBeInTheDocument();
    expect(mocks.workflow).toHaveBeenCalledOnce();
    expect(mocks.saveWorkflow).not.toHaveBeenCalled();
    client.clear();
});

it('saving a prompt refreshes source without discarding unsaved model repairs in that column', async () => {
    mocks.knowledge.mockResolvedValueOnce({ data: knowledge, inherited_from_root: true })
        .mockResolvedValue({ data: { ...knowledge, abstract_prompt: 'saved prompt' }, inherited_from_root: false });
    mocks.saveKnowledge.mockResolvedValue(undefined);
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><KnowledgeModel llmOptions={options} embeddings={options} onBack={vi.fn()} /></QueryClientProvider>);
    await screen.findByRole('button', { name: 'model.saveLocalConfiguration' });
    fireEvent.change(screen.getByRole('combobox', { name: 'model.documentSummaryModel' }), { target: { value: '7' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'model.editPromptButton' })[0]);
    fireEvent.change(await screen.findByRole('textbox'), { target: { value: 'saved prompt' } });
    fireEvent.click(screen.getByRole('button', { name: 'model.save' }));
    await waitFor(() => expect(mocks.saveKnowledge).toHaveBeenCalledWith({ ...knowledge, abstract_prompt: 'saved prompt' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('combobox', { name: 'model.documentSummaryModel' })).toHaveValue('7');
    expect(screen.queryByText('model.systemConfigInheritedBadge')).not.toBeInTheDocument();
    client.clear();
});
