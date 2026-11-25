import axios from '../request';
import type { WorkFlow } from '@/types/flow';

export interface WorkflowReferenceError {
    node_id?: string;
    node_name?: string;
    parameter_key?: string;
    resource_type: string;
    target_id: string;
    state: string;
}

interface WorkflowReferenceResult {
    valid: boolean;
    errors: WorkflowReferenceError[];
}

export async function validateWorkflowReferences(flow: WorkFlow): Promise<WorkflowReferenceResult> {
    const result = await axios.post<unknown, WorkflowReferenceResult>('/api/v1/workflow/references/validate', {
        workflow_id: flow.id,
        data: { nodes: flow.nodes, edges: flow.edges },
    }, { timeout: 15000 });
    if (typeof result?.valid !== 'boolean' || !Array.isArray(result.errors)
        || result.valid !== (result.errors.length === 0)
        || result.errors.some(item => !item || typeof item.target_id !== 'string' || typeof item.state !== 'string')) {
        throw new Error('invalid_workflow_preflight_response');
    }
    return result;
}
