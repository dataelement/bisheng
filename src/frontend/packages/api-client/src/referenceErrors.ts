import { referenceReasonKeys } from './referenceReasons';

type Translate = (key: string, values?: Record<string, string>) => string;

const resources = new Set(['model', 'rerank_model', 'knowledge_space', 'qa_knowledge', 'knowledge_file']);
const states = new Set(['invalid_missing', 'invalid_legacy', 'invalid_deleted', 'deleting', 'invalid_scope', 'unavailable', 'offline', 'type_mismatch']);
const detailReasons = new Set(['reference_target_invalid', 'model_selection_unavailable', 'knowledge_reference_target_unavailable', 'model_reference_target_unavailable', 'model_default_models_unavailable']);

/** Render only authorized selections and allowlisted states, identically for HTTP and WS. */
export function referenceErrorMessage(envelope: unknown, translate: Translate): string {
    if (!envelope || typeof envelope !== 'object') return '';
    const { status_code: code, data } = envelope as { status_code?: unknown; data?: unknown };
    if (code !== 10996 || !data || typeof data !== 'object') return '';
    const { reason, reference_errors: current, workflow_reference_errors: legacy } = data as Record<string, unknown>;
    if (typeof reason !== 'string') return '';
    const render: Translate = (key, values) => {
        const result = translate(key, values);
        return typeof result === 'string' && result.trim() && ![key, `api_errors.${key}`, `api_errors:${key}`, 'undefined'].includes(result) ? result : '';
    };
    const details = Array.isArray(current) && current.length ? current : legacy;
    const messages: string[] = [];
    if (detailReasons.has(reason) && Array.isArray(details)) {
        for (const detail of details.slice(0, 5)) {
            if (!detail || typeof detail !== 'object') continue;
            const { node_name: nodeName, resource_type: type, target_id: targetId, state } = detail;
            if (typeof type !== 'string' || !resources.has(type)
                || typeof targetId !== 'string' || !/^[1-9]\d{0,63}$/.test(targetId)) continue;
            if (nodeName !== undefined && (typeof nodeName !== 'string' || !nodeName.trim() || nodeName.length > 100)) continue;
            if (state === undefined && details === legacy && nodeName && type !== 'knowledge_file') {
                const message = render(`workflow_reference_${type}`, { nodeName, targetId });
                if (message) messages.push(message);
                continue;
            }
            if (typeof state !== 'string' || !states.has(state)) continue;
            const nodeId = typeof detail.node_id === 'string' && /^[\w-]{1,100}$/.test(detail.node_id) ? detail.node_id : '';
            const location = nodeName ? (nodeId ? render('reference_node_with_id', { nodeName, nodeId }) : render('reference_node', { nodeName })) : '';
            const resource = render(`reference_resource_${type}`);
            if (!resource || (nodeName && !location)) continue;
            const message = render(`reference_state_${state}`, { location, resource, targetId });
            if (message) messages.push(message);
        }
    }
    if (messages.length) return [...new Set(messages)].join('\n');
    const group = referenceReasonKeys.get(reason);
    return group ? render(`reference_reason_${group}`) : '';
}
