import type { useLocalize } from '~/hooks';
import { parseKnowledgeTarget } from '~/utils/failureInfo';

interface KnowledgeStep {
    name: string;
    stepType?: string;
    params?: Record<string, unknown> | null;
    extraInfo?: Record<string, unknown>;
}

export function knowledgeStepTitle(step: KnowledgeStep, localize: ReturnType<typeof useLocalize>): string | undefined {
    if (step.stepType !== 'knowledge' && !['search_knowledge_base', 'search_knowledge_bases'].includes(step.name.toLowerCase())) return undefined;
    const actualId = step.params?.knowledge_id;
    const target = actualId == null ? undefined : parseKnowledgeTarget(step.extraInfo?.knowledge_target, actualId);
    if (target?.kind === 'personal') return localize('com_linsight.knowledge_target_personal');
    const kind = target?.kind === 'space' ? 'space' : 'knowledge_base';
    return localize(`com_linsight.knowledge_target_${kind}${target?.name ? '_named' : ''}`, { 0: target?.name });
}
