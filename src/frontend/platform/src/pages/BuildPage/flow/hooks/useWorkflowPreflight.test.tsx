import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { WorkFlow } from '@/types/flow';
import { validateWorkflowReferences } from '@/controllers/API/workflowReferences';
import useFlowStore from '../flowStore';
import { applyWorkflowReferenceErrors, useWorkflowPreflight } from './useWorkflowPreflight';
import { useKnowledgeReferenceErrors } from './useKnowledgeReferenceErrors';

vi.mock('@/controllers/API/workflowReferences', () => ({ validateWorkflowReferences: vi.fn() }));

function flow(): WorkFlow {
    return { id: 'workflow', name: 'draft', description: '', viewport: { x: 0, y: 0, zoom: 1 }, edges: [], nodes: [
        { id: 'rag_a', position: { x: 0, y: 0 }, data: { id: 'rag_a', name: 'rag', type: 'rag', group_params: [
            { params: [{ key: 'knowledge', value: { type: 'space', value: [{ key: 4, label: 'saved space' }] } }] },
        ] } },
    ] };
}
const issue = { node_id: 'rag_a', node_name: 'rag', parameter_key: 'knowledge', target_id: '4', resource_type: 'knowledge_space', state: 'invalid_missing' };
const api = vi.mocked(validateWorkflowReferences);
beforeEach(() => {
    vi.clearAllMocks();
    useFlowStore.setState({ flow: flow() });
    api.mockResolvedValue({ valid: true, errors: [] });
});
afterEach(cleanup);

it('marks the exact selection and blocks the connection callback on a missing target', async () => {
    api.mockResolvedValue({ valid: false, errors: [issue] });
    const current = useFlowStore.getState().flow;
    const { result } = renderHook(() => ({
        run: useWorkflowPreflight(current),
        errors: useKnowledgeReferenceErrors('rag_a', 'knowledge', ['4']),
    }));
    const openConnection = vi.fn();
    await act(async () => {
        expect(await result.current.run.validate(async () => [], openConnection)).toEqual(['referencePreflight.issue']);
    });
    expect(result.current.errors).toEqual([issue]);
    expect(openConnection).not.toHaveBeenCalled();
});

it('awaits the HTTP check and only opens a connection with the validated snapshot', async () => {
    let finish!: (result: { valid: boolean; errors: typeof issue[] }) => void;
    api.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const current = useFlowStore.getState().flow;
    const { result } = renderHook(() => useWorkflowPreflight(current));
    const openConnection = vi.fn();
    let pending!: Promise<string[]>;
    await act(async () => { pending = result.current.validate(async () => [], openConnection); });
    expect(result.current.validating).toBe(true);
    expect(openConnection).not.toHaveBeenCalled();
    await act(async () => { await result.current.validate(async () => [], openConnection); });
    expect(api).toHaveBeenCalledTimes(1);
    await act(async () => { finish({ valid: true, errors: [] }); await pending; });
    expect(openConnection).toHaveBeenCalledTimes(1);
    expect(openConnection).toHaveBeenCalledWith(current);
    expect(openConnection.mock.calls[0][0]).not.toBe(current);
    expect(result.current.validating).toBe(false);
});

it('does not start when an in-place unsaved edit races the preflight', async () => {
    let finish!: (result: { valid: boolean; errors: typeof issue[] }) => void;
    api.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const current = useFlowStore.getState().flow;
    const { result } = renderHook(() => useWorkflowPreflight(current));
    const openConnection = vi.fn();
    let pending!: Promise<string[]>;
    await act(async () => { pending = result.current.validate(async () => [], openConnection); });
    (current.nodes[0].data as { name: string }).name = 'edited while validating';
    await act(async () => {
        finish({ valid: true, errors: [] });
        expect(await pending).toEqual(['referencePreflight.changed']);
    });
    expect(openConnection).not.toHaveBeenCalled();
});

it('does not start or mark deletion when the API times out', async () => {
    api.mockRejectedValue(new Error('timeout'));
    const current = useFlowStore.getState().flow;
    const { result } = renderHook(() => ({ run: useWorkflowPreflight(current), errors: useKnowledgeReferenceErrors('rag_a', 'knowledge', ['4']) }));
    const openConnection = vi.fn();
    await act(async () => {
        expect(await result.current.run.validate(async () => [], openConnection)).toEqual(['referencePreflight.failed']);
    });
    expect(result.current.errors).toEqual([]);
    expect(openConnection).not.toHaveBeenCalled();
    expect(result.current.run.validating).toBe(false);
});

it('keeps local validation before HTTP and never connects after a local error', async () => {
    const { result } = renderHook(() => useWorkflowPreflight(useFlowStore.getState().flow));
    const openConnection = vi.fn();
    await act(async () => {
        expect(await result.current.validate(async () => ['required'], openConnection)).toEqual(['required']);
    });
    expect(api).not.toHaveBeenCalled();
    expect(openConnection).not.toHaveBeenCalled();
});

it('checks the current unsaved node selection rather than the saved flow or candidate list', async () => {
    const current = useFlowStore.getState().flow;
    current.nodes.push({ id: 'other', position: { x: 0, y: 0 }, data: {} });
    const { result } = renderHook(() => useWorkflowPreflight(current, 'rag_a'));
    await act(async () => { await result.current.validate(async () => [], vi.fn()); });
    expect(api.mock.calls[0][0].nodes.map(node => node.id)).toEqual(['rag_a']);
    expect(api.mock.calls[0][0].nodes[0].data).toEqual(current.nodes[0].data);
});

it('does not attach a server error to another field or retain it after removing the selection', () => {
    const { result, rerender } = renderHook(({ ids }) => ({
        selected: useKnowledgeReferenceErrors('rag_a', 'knowledge', ids),
        another: useKnowledgeReferenceErrors('rag_a', 'qa_knowledge_id', ids),
    }), { initialProps: { ids: ['4'] } });
    act(() => applyWorkflowReferenceErrors([issue]));
    expect(result.current.selected).toEqual([issue]);
    expect(result.current.another).toEqual([]);
    rerender({ ids: ['5'] });
    expect(result.current.selected).toEqual([]);
});
