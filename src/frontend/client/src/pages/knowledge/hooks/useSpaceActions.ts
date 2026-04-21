import { useQueryClient } from "@tanstack/react-query";
import {
    KnowledgeSpace,
    SortType,
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
    createdSortBy: SortType;
    joinedSortBy: SortType;
    departmentSortBy: SortType;
    createdSpaces: KnowledgeSpace[];
    joinedSpaces: KnowledgeSpace[];
    departmentSpaces: KnowledgeSpace[];
    onSpaceSelect: (space: KnowledgeSpace | null) => void;
}

/**
 * Extracts knowledge-space CRUD operations with optimistic-update logic
 * from KnowledgeSpaceSidebar, keeping the sidebar focused on UI.
 * Mirrors useChannelActions from the Subscription module.
 */
export function useSpaceActions({
    activeSpaceId,
    createdSortBy,
    joinedSortBy,
    departmentSortBy,
    createdSpaces,
    joinedSpaces,
    departmentSpaces,
    onSpaceSelect,
}: UseSpaceActionsOptions) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();

    // ── Cache updaters scoped to current sort keys ──

    const updateCreatedCache = (updater: (list: KnowledgeSpace[]) => KnowledgeSpace[]) => {
        queryClient.setQueryData(["knowledgeSpaces", "mine", createdSortBy], (old: KnowledgeSpace[] = []) => updater(old));
    };

    const updateJoinedCache = (updater: (list: KnowledgeSpace[]) => KnowledgeSpace[]) => {
        queryClient.setQueryData(["knowledgeSpaces", "joined", joinedSortBy], (old: KnowledgeSpace[] = []) => updater(old));
    };

    const updateDepartmentCache = (updater: (list: KnowledgeSpace[]) => KnowledgeSpace[]) => {
        queryClient.setQueryData(["knowledgeSpaces", "department", departmentSortBy], (old: KnowledgeSpace[] = []) => updater(old));
    };

    const updateAllCaches = (updater: (list: KnowledgeSpace[]) => KnowledgeSpace[]) => {
        updateCreatedCache(updater);
        updateJoinedCache(updater);
        updateDepartmentCache(updater);
    };

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

        // Optimistic remove from created list
        queryClient.setQueryData(
            ["knowledgeSpaces", "mine", createdSortBy],
            (old: KnowledgeSpace[] = []) => {
                const newData = old.filter(s => s.id !== spaceId);
                if (activeSpaceId === spaceId && newData.length > 0) nextActive = newData[0];
                return newData;
            }
        );

        // Also check joined list for fallback selection
        if (activeSpaceId === spaceId && !nextActive) {
            const joined = queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "joined", joinedSortBy]) || [];
            const newJoined = joined.filter(s => s.id !== spaceId);
            queryClient.setQueryData(["knowledgeSpaces", "joined", joinedSortBy], newJoined);
            if (newJoined.length > 0) nextActive = newJoined[0];
        } else {
            queryClient.setQueryData(
                ["knowledgeSpaces", "joined", joinedSortBy],
                (old: KnowledgeSpace[] = []) => old.filter(s => s.id !== spaceId)
            );
        }

        // Also check department list for fallback selection
        if (activeSpaceId === spaceId && !nextActive) {
            const dept = queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "department", departmentSortBy]) || [];
            const newDept = dept.filter(s => s.id !== spaceId);
            queryClient.setQueryData(["knowledgeSpaces", "department", departmentSortBy], newDept);
            if (newDept.length > 0) nextActive = newDept[0];
        } else {
            queryClient.setQueryData(
                ["knowledgeSpaces", "department", departmentSortBy],
                (old: KnowledgeSpace[] = []) => old.filter(s => s.id !== spaceId)
            );
        }

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

        // Optimistic remove from joined list
        queryClient.setQueryData(
            ["knowledgeSpaces", "joined", joinedSortBy],
            (old: KnowledgeSpace[] = []) => {
                const newData = old.filter(s => s.id !== spaceId);
                if (activeSpaceId === spaceId && newData.length > 0) nextActive = newData[0];
                return newData;
            }
        );

        if (activeSpaceId === spaceId) {
            if (!nextActive && createdSpaces.length > 0) nextActive = createdSpaces[0];
            onSpaceSelect(nextActive);
        }

        try {
            await unsubscribeSpaceApi(spaceId);
            showToast({ message: localize("com_knowledge.exited_space"), severity: NotificationSeverity.SUCCESS });
        } catch {
            queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces", "joined"] });
            showToast({ message: localize("com_knowledge.exit_space_failed"), severity: NotificationSeverity.ERROR });
        }
    };

    // ── Pin / Unpin space ──

    const handlePinSpace = async (spaceId: string, pinned: boolean, type: "created" | "joined" | "department") => {
        const targetList = type === "created" ? createdSpaces : type === "department" ? departmentSpaces : joinedSpaces;
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
