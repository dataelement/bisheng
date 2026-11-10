import request from '../request';
import type { KnowledgeCapabilities, KnowledgeResource } from '@/types/flow/platformKnowledge';

const root = '/api/v1/workflow/platform-knowledge';

export async function getKnowledgeCapabilities(): Promise<KnowledgeCapabilities> {
    const env = await request.get<unknown, { workflow: KnowledgeCapabilities; multi_tenant_enabled?: boolean }>('/api/v1/env');
    return { ...env.workflow, multi_tenant_enabled: env.multi_tenant_enabled };
}

export async function listPlatformKnowledge(workflowId: string, cursor?: string): Promise<{
    items: KnowledgeResource[];
    next_cursor: string | null;
}> {
    return await request.get(root, { params: { workflow_id: workflowId, cursor } });
}

export async function getPlatformKnowledge(workflowId: string, resourceId: string): Promise<KnowledgeResource> {
    return await request.get(root + '/' + encodeURIComponent(resourceId), { params: { workflow_id: workflowId } });
}

export async function validatePlatformKnowledge(workflowId: string, graph: unknown, nodeId: string): Promise<{ valid: boolean }> {
    return await request.post(root + '/validate', { workflow_id: workflowId, graph, node_id: nodeId });
}

export const knowledgeOutputs = ['retrieved_result', 'retrieved_text', 'citations', 'hit_count'].map(key => ({ key, label: key }));

export const platformKnowledgeTemplate = {
    id: 'platform_knowledge_xxx',
    type: 'platform_knowledge_retriever',
    name: '',
    description: '',
    v: 1,
    group_params: [
        { name: '', params: [
            { key: 'user_question', type: 'platform_knowledge_query', required: true, value: { source: 'variable', variable: '' } },
            { key: 'knowledge', type: 'platform_knowledge_select', required: true, value: null },
            { key: 'top_k', label: 'true', type: 'number', required: true, value: 5, min: 1, max: 20 },
        ] },
        { name: '', params: [
            { key: 'retrieved_result', type: 'var', value: knowledgeOutputs, global: 'code:value.map(el => ({ label: el.label, value: el.key }))' },
        ] },
    ],
};
