import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SaveQaLibForm from './SaveQaLibForm'
import AddSimilarQuestions from './AddSimilarQuestions'
import type { AnnotationFormHandle } from './annotationTypes'

const mock = vi.hoisted(() => ({ update: vi.fn(), add: vi.fn(), list: vi.fn(), generate: vi.fn(), message: vi.fn() }))
vi.mock('@/controllers/API', () => ({ updateQa: mock.update, addSimilarQa: mock.add, getQaList: mock.list, generateSimilarQa: mock.generate }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (p: Promise<unknown>) => p.catch(() => false) }))
vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({ useToast: () => ({ message: mock.message }) }))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
})
vi.mock('@/components/bs-comp/selectComponent/knowledge', () => ({ default: ({ onChange }: { onChange: (value: { value: string }[]) => void }) => <button onClick={() => onChange([{ value: 'qa-1' }])}>Select knowledge</button> }))
afterEach(cleanup)
beforeEach(() => {
    vi.clearAllMocks()
    mock.update.mockResolvedValue({})
    mock.add.mockResolvedValue({})
    mock.generate.mockResolvedValue({ questions: ['Generated question'] })
    mock.list.mockResolvedValue({ total: 1, data: [{ id: 123, questions: 'Existing question', answers: 'Existing answer' }] })
})
function openForm(Component: typeof SaveQaLibForm) {
    const ref = createRef<AnnotationFormHandle>()
    const onMarked = vi.fn()
    render(<Component ref={ref} onMarked={onMarked} />)
    act(() => ref.current?.open('message-1', { q: 'Question', a: 'Answer' }))
    return { ref, onMarked }
}
it('preserves new-QA validation and the save payload', async () => {
    const { onMarked } = openForm(SaveQaLibForm)
    fireEvent.click(screen.getByRole('button', { name: 'log.confirm' }))
    expect(mock.update).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('Select knowledge'))
    fireEvent.click(screen.getByRole('button', { name: 'log.confirm' }))
    await waitFor(() => expect(mock.update).toHaveBeenCalledWith('', { questions: ['Question'], answers: ['Answer'], knowledge_id: 'qa-1', source: 2 }))
    await waitFor(() => expect(onMarked).toHaveBeenCalledTimes(1))
})
it('adds generated similar questions to the saved QA without losing the original', async () => {
    openForm(SaveQaLibForm)
    fireEvent.click(screen.getByText('Select knowledge'))
    fireEvent.click(screen.getByRole('button', { name: 'log.aiGenerate' }))
    await waitFor(() => expect(mock.generate).toHaveBeenCalledWith('Question', 'Answer'))
    await screen.findByDisplayValue('Generated question')
    fireEvent.click(screen.getByRole('button', { name: 'log.confirm' }))
    await waitFor(() => expect(mock.update).toHaveBeenCalledWith('', expect.objectContaining({ questions: ['Question', 'Generated question'] })))
})
it('submits only checked existing-QA IDs and clears them on reopening', async () => {
    const { ref, onMarked } = openForm(AddSimilarQuestions)
    fireEvent.click(screen.getByRole('button', { name: 'log.confirm' }))
    expect(mock.add).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('Select knowledge'))
    const checkbox = await screen.findByRole('checkbox', { name: 'Existing question' })
    fireEvent.click(checkbox)
    expect(checkbox).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(checkbox)
    expect(checkbox).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(checkbox)
    fireEvent.click(screen.getByRole('button', { name: 'log.confirm' }))
    await waitFor(() => expect(mock.add).toHaveBeenCalledWith({ ids: [123], question: 'Question' }))
    await waitFor(() => expect(onMarked).toHaveBeenCalledTimes(1))
    act(() => ref.current?.open('message-2', { q: 'Another question', a: 'Answer' }))
    fireEvent.click(screen.getByRole('button', { name: 'log.confirm' }))
    expect(mock.add).toHaveBeenCalledTimes(1)
})


it('keeps a reopened QA dialog and returns the captured origin after an earlier save completes', async () => {
    let resolveSave: (value: unknown) => void = () => undefined;
    mock.update.mockImplementationOnce(() => new Promise(resolve => { resolveSave = resolve; }));
    const ref = createRef<AnnotationFormHandle>();
    const onMarked = vi.fn();
    render(<SaveQaLibForm ref={ref} onMarked={onMarked} />);
    const origin = { taskId: 'task-a', conversationId: 'a', sourceMessageId: 'message-a', actionId: 'save-a', sessionGeneration: 1 };
    act(() => ref.current?.open('message-a', { q: 'A question', a: 'A answer' }, origin));
    fireEvent.click(screen.getByText('Select knowledge'));
    fireEvent.click(screen.getByRole('button', { name: 'log.confirm' }));
    act(() => ref.current?.open('message-b', { q: 'B question', a: 'B answer' }, { ...origin, conversationId: 'b', actionId: 'save-b', sessionGeneration: 2 }));
    await act(async () => { resolveSave({}); });
    expect(onMarked).toHaveBeenCalledWith(origin);
    expect(screen.getByDisplayValue('B question')).toBeTruthy();
    expect(screen.getByRole('dialog')).toBeTruthy();
});

it('does not append generated questions to a reopened dialog', async () => {
    let resolveGenerate: (value: unknown) => void = () => undefined;
    mock.generate.mockImplementationOnce(() => new Promise(resolve => { resolveGenerate = resolve; }));
    const { ref } = openForm(SaveQaLibForm);
    fireEvent.click(screen.getByRole('button', { name: 'log.aiGenerate' }));
    act(() => ref.current?.open('message-b', { q: 'B question', a: 'B answer' }));
    await act(async () => { resolveGenerate({ questions: ['Late A question'] }); });
    expect(screen.queryByDisplayValue('Late A question')).toBeNull();
    expect(screen.getByDisplayValue('B question')).toBeTruthy();
});


it('keeps a failed new-QA write editable and never reports completion', async () => {
    mock.update.mockRejectedValueOnce(new Error('write failed'));
    const { onMarked } = openForm(SaveQaLibForm);
    fireEvent.click(screen.getByText('Select knowledge'));
    fireEvent.click(screen.getByRole('button', { name: 'log.confirm' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'log.confirm' })).toBeEnabled());
    expect(onMarked).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('Question')).toBeTruthy();
});

it('returns the original similar-question operation without closing a reopened dialog', async () => {
    let resolveSave: (value: unknown) => void = () => undefined;
    mock.add.mockImplementationOnce(() => new Promise(resolve => { resolveSave = resolve; }));
    const ref = createRef<AnnotationFormHandle>(); const onMarked = vi.fn();
    render(<AddSimilarQuestions ref={ref} onMarked={onMarked} />);
    const origin = { taskId: 'task-a', conversationId: 'a', sourceMessageId: 'question-a', actionId: 'similar-a', sessionGeneration: 1 };
    act(() => ref.current?.open('question-a', { q: 'Question A', a: '' }, origin));
    fireEvent.click(screen.getByText('Select knowledge'));
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Existing question' }));
    fireEvent.click(screen.getByRole('button', { name: 'log.confirm' }));
    act(() => ref.current?.open('question-b', { q: 'Question B', a: '' }, { ...origin, conversationId: 'b', actionId: 'similar-b', sessionGeneration: 2 }));
    await act(async () => { resolveSave({}); });
    expect(mock.add).toHaveBeenCalledWith({ ids: [123], question: 'Question A' });
    expect(onMarked).toHaveBeenCalledWith(origin);
    expect(screen.getByRole('dialog')).toBeTruthy();
});
