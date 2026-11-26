import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { validateWorkflowReferences, type WorkflowReferenceError } from '@/controllers/API/workflowReferences';
import type { WorkFlow } from '@/types/flow';
import useFlowStore from '../flowStore';

export const REFERENCE_VALIDATION_EVENT = 'workflowReferenceValidation';

function selectedGraph(flow: WorkFlow, nodeId?: string): WorkFlow {
    return nodeId ? { ...flow, nodes: flow.nodes.filter(node => node.id === nodeId), edges: [] } : flow;
}

function signature(flow: WorkFlow): string {
    return JSON.stringify({ id: flow.id, nodes: flow.nodes, edges: flow.edges });
}

export function applyWorkflowReferenceErrors(errors: WorkflowReferenceError[]) {
    window.dispatchEvent(new CustomEvent(REFERENCE_VALIDATION_EVENT, { detail: errors }));
    window.dispatchEvent(new CustomEvent('nodeErrorBorderEvent', {
        detail: { nodeIds: [...new Set(errors.map(item => item.node_id).filter(Boolean))] },
    }));
}

export function useWorkflowPreflight(flow: WorkFlow, nodeId?: string) {
    const { t } = useTranslation('flow');
    const [validating, setValidating] = useState(false);
    const pending = useRef(false);
    const latestFlow = useRef(flow);
    latestFlow.current = flow;

    const validate = async (
        localCheck: () => Promise<string[]>,
        onValid: (snapshot: WorkFlow) => void,
    ): Promise<string[]> => {
        if (pending.current) return [];
        pending.current = true;
        setValidating(true);
        try {
            const selected = selectedGraph(flow, nodeId);
            const expected = signature(selected);
            const snapshot = JSON.parse(JSON.stringify(selected)) as WorkFlow;
            const localErrors = await localCheck();
            if (localErrors.length) return localErrors;
            applyWorkflowReferenceErrors([]);
            const result = await validateWorkflowReferences(snapshot);
            const current = useFlowStore.getState().flow ?? latestFlow.current;
            if (signature(selectedGraph(current, nodeId)) !== expected) return [t('referencePreflight.changed')];
            applyWorkflowReferenceErrors(result.errors);
            if (!result.valid) return result.errors.map(item => {
                const node = snapshot.nodes.find(candidate => candidate.id === item.node_id);
                const data = node?.data as { name?: string; group_params?: { params: { key: string; value?: unknown }[] }[] } | undefined;
                const param = data?.group_params?.flatMap(group => group.params).find(value => value.key === item.parameter_key);
                const selection = Array.isArray(param?.value) ? param.value
                    : (param?.value as { value?: unknown } | undefined)?.value;
                const label = Array.isArray(selection)
                    ? (selection as { key: string | number; label: string }[]).find(value => String(value.key) === item.target_id)?.label
                    : undefined;
                const missing = ['invalid_missing', 'invalid_deleted', 'invalid_legacy'].includes(item.state);
                return t('referencePreflight.issue', {
                    node: data?.name ?? item.node_name ?? item.node_id ?? '',
                    label: label ?? item.target_id,
                    id: item.target_id,
                    state: t(missing ? 'referencePreflight.missing' : 'referencePreflight.unavailable'),
                });
            });
            onValid(snapshot);
            return [];
        } catch {
            // Transport failures never become resource-deletion facts or permit execution.
            return [t('referencePreflight.failed')];
        } finally {
            pending.current = false;
            setValidating(false);
        }
    };
    return { validate, validating };
}
