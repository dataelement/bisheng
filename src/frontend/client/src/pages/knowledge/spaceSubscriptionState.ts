import { SPACE_CHILDREN_STATUS_SUCCESS_ONLY, SpaceRole } from '~/api/knowledge';
import type { KnowledgeSpace } from '~/api/knowledge';

export type SpaceJoinStatus = 'none' | 'joined' | 'pending' | 'rejected';

export function resolveSpaceJoinStatus(info: KnowledgeSpace): SpaceJoinStatus {
    const status = String(info.subscriptionStatus ?? info.squareStatus ?? '').toLowerCase();
    if (status === 'rejected') return 'rejected';
    if (info.isPending || status === 'pending') return 'pending';
    if (info.isFollowed || status === 'subscribed' || status === 'joined') return 'joined';
    return 'none';
}

export function getPreviewFileStatusFilter(space: KnowledgeSpace): number[] | undefined {
    if (space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN) return undefined;
    return SPACE_CHILDREN_STATUS_SUCCESS_ONLY;
}

export function getSpaceJoinButton(status: SpaceJoinStatus, isPublic: boolean, subscribing: boolean) {
    if (status === 'joined') return { label: 'com_knowledge.joined' as const, variant: 'secondary' as const, disabled: true };
    if (status === 'pending') return { label: 'com_knowledge.pending' as const, variant: 'secondary' as const, disabled: true };
    if (status === 'rejected') return { label: 'com_knowledge.reapply' as const, variant: 'outline' as const, disabled: subscribing };
    return { label: 'com_knowledge.join' as const, variant: isPublic ? 'default' as const : 'outline' as const, disabled: subscribing };
}
