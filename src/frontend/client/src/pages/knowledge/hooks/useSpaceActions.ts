import { useQueryClient } from "@tanstack/react-query";
import {
    KnowledgeSpace,
    GroupedKnowledgeSpaces,
    SpaceLevel,
    updateSpaceApi,
    deleteSpaceApi,
    unsubscribeSpaceApi,
    pinSpaceApi,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";

interface UseSpaceActionsOptions {
    activeSpaceId?: string;
    groupedSpaces: GroupedKnowledgeSpaces;
    onSpaceSelect: (space: KnowledgeSpace | null) => void;
}

/**
 * Extracts knowledge-space CRUD operations with optimistic-update logic
 * from KnowledgeSpaceSidebar, keeping the sidebar focused on UI.
 * Mirrors useChannelActions from the Subscription module.
 */
export function useSpaceActions({
    activeSpaceId,
    groupedSpaces,
    onSpaceSelect,
}: UseSpaceActionsOptions) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();

    // ── Cache updaters scoped to current sort keys ──

    const updateAllCaches = (updater: (list: KnowledgeSpace[]) => KnowledgeSpace[]) => {
        queryClient.setQueryData(
            ["knowledgeSpaces", "grouped"],
            (old: GroupedKnowledgeSpaces | undefined) => {
                if (!old) return old;
                return {
                    publicSpaces: updater(old.publicSpaces),
                    departmentSpaces: updater(old.departmentSpaces),
                    teamSpaces: updater(old.teamSpaces),
                    personalSpaces: updater(old.personalSpaces),
                };
            },
        );
    };

    const allSpaces = [
        ...groupedSpaces.publicSpaces,
        ...groupedSpaces.departmentSpaces,
        ...groupedSpaces.teamSpaces,
        ...groupedSpaces.personalSpaces,
    ];

    // ── Rename space (double-click inline edit) ──

    const handleUpdateSpace = async (space: KnowledgeSpace) => {
        // Optimistic update
        updateAllCaches(list => list.map(s => s.id === space.id ? space : s));
        if (activeSpaceId === space.id) {
            onSpaceSelect(space);
        }

        try {
            await updateSpaceApi(space.id, {
                name: space.name,
                description: space.description,
                icon: space.icon,
                auth_type: space.visibility,
                is_released: space.isReleased,
            });
            showToast({ message: localize("com_knowledge.space_updated"), severity: NotificationSeverity.SUCCESS });
        } catch {
            // Rollback on failure
            queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: localize("com_knowledge.update_space_failed"), severity: NotificationSeverity.ERROR });
        }
    };

    // ── Delete space ──

    const handleDeleteSpace = async (spaceId: string) => {
        let nextActive: KnowledgeSpace | null = null;

        updateAllCaches((list) => list.filter(s => s.id !== spaceId));
        nextActive = allSpaces.find(s => s.id !== spaceId) ?? null;

        if (activeSpaceId === spaceId) {
            onSpaceSelect(nextActive);
        }

        try {
            await deleteSpaceApi(spaceId);
            queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: localize("com_knowledge.space_deleted"), severity: NotificationSeverity.SUCCESS });
        } catch {
            queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: localize("com_knowledge.delete_space_failed"), severity: NotificationSeverity.ERROR });
        }
    };

    // ── Leave (unsubscribe from) space ──

    const handleLeaveSpace = async (spaceId: string) => {
        let nextActive: KnowledgeSpace | null = null;

        updateAllCaches((list) => list.filter(s => s.id !== spaceId));

        if (activeSpaceId === spaceId) {
            nextActive = allSpaces.find(s => s.id !== spaceId) ?? null;
            onSpaceSelect(nextActive);
        }

        try {
            await unsubscribeSpaceApi(spaceId);
            showToast({ message: localize("com_knowledge.exited_space"), severity: NotificationSeverity.SUCCESS });
        } catch {
            queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: localize("com_knowledge.exit_space_failed"), severity: NotificationSeverity.ERROR });
        }
    };

    // ── Pin / Unpin space ──

    const handlePinSpace = async (spaceId: string, pinned: boolean, type: SpaceLevel) => {
        const targetList =
            type === SpaceLevel.PUBLIC ? groupedSpaces.publicSpaces
                : type === SpaceLevel.DEPARTMENT ? groupedSpaces.departmentSpaces
                    : type === SpaceLevel.TEAM ? groupedSpaces.teamSpaces
                        : groupedSpaces.personalSpaces;
        if (pinned && targetList.filter(s => s.isPinned).length >= 5) {
            showToast({ message: localize("com_knowledge.pin_limit_reached"), severity: NotificationSeverity.INFO });
            return;
        }

        // Optimistic update
        const updater = (list: KnowledgeSpace[]) => list.map(s => s.id === spaceId ? { ...s, isPinned: pinned } : s);
        updateAllCaches(updater);

        if (activeSpaceId === spaceId) {
            const space = targetList.find(s => s.id === spaceId);
            if (space) onSpaceSelect({ ...space, isPinned: pinned });
        }

        try {
            await pinSpaceApi(spaceId, pinned);
            queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: pinned ? localize("com_knowledge.pinned") : localize("com_knowledge.unpinned"), severity: NotificationSeverity.SUCCESS });
        } catch {
            // Rollback
            const rollback = (list: KnowledgeSpace[]) => list.map(s => s.id === spaceId ? { ...s, isPinned: !pinned } : s);
            updateAllCaches(rollback);
            if (activeSpaceId === spaceId) {
                const space = targetList.find(s => s.id === spaceId);
                if (space) onSpaceSelect({ ...space, isPinned: !pinned });
            }
            showToast({ message: localize("com_knowledge.operation_failed"), severity: NotificationSeverity.ERROR });
        }
    };

    return {
        handleUpdateSpace,
        handleDeleteSpace,
        handleLeaveSpace,
        handlePinSpace,
    };
}
