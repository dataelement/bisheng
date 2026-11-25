import { useEffect, useState } from 'react';
import type { WorkflowReferenceError } from '@/controllers/API/workflowReferences';
import { REFERENCE_VALIDATION_EVENT } from './useWorkflowPreflight';

/** Only server-confirmed results may mark a saved selection as invalid. */
export function useKnowledgeReferenceErrors(nodeId: string, parameterKey: string, selectedIds: string[]) {
    const [errors, setErrors] = useState<WorkflowReferenceError[]>([]);
    const selectionKey = JSON.stringify(selectedIds);
    useEffect(() => { setErrors([]); }, [selectionKey]);
    useEffect(() => {
        const receive = (event: Event) => {
            setErrors((event as CustomEvent<WorkflowReferenceError[]>).detail.filter(item =>
                item.node_id === nodeId && item.parameter_key === parameterKey));
        };
        window.addEventListener(REFERENCE_VALIDATION_EVENT, receive);
        return () => window.removeEventListener(REFERENCE_VALIDATION_EVENT, receive);
    }, [nodeId, parameterKey]);
    return errors.filter(item => selectedIds.includes(item.target_id));
}
