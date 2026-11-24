import i18next from 'i18next';

const resourceTypes = new Set(['model', 'rerank_model', 'knowledge_space', 'qa_knowledge']);
const reasons = new Set(['model_selection_unavailable', 'knowledge_reference_target_unavailable']);

export function workflowReferenceErrorMessage(envelope: unknown): string {
    if (!envelope || typeof envelope !== 'object') return '';
    const { status_code: code, data } = envelope as { status_code?: unknown; data?: unknown };
    if (code !== 10996 || !data || typeof data !== 'object') return '';
    const { reason, workflow_reference_errors: details } = data as Record<string, unknown>;
    if (typeof reason !== 'string' || !reasons.has(reason) || !Array.isArray(details)) return '';
    const messages: string[] = [];
    for (const detail of details.slice(0, 5)) {
        if (!detail || typeof detail !== 'object') continue;
        const { node_name: nodeName, resource_type: resourceType, target_id: targetId } = detail;
        if (typeof nodeName !== 'string' || !nodeName.trim() || nodeName.length > 100
            || typeof resourceType !== 'string' || !resourceTypes.has(resourceType)
            || typeof targetId !== 'string' || !/^[1-9]\d{0,63}$/.test(targetId)) continue;
        const key = `api_errors:workflow_reference_${resourceType}`;
        if (!i18next.exists(key)) continue;
        messages.push(String(i18next.t(key, { nodeName, targetId })));
    }
    return [...new Set(messages)].join('\n');
}
