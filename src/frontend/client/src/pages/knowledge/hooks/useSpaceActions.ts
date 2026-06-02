import { useQueryClient } from "@tanstack/react-query";
import {
    KnowledgeSpace,
    SpaceSortType,
    updateSpaceApi,
    deleteSpaceApi,
    unsubscribeSpaceApi,
    pinSpaceApi,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";

const ORGANIZATION_GRANT_EXIT_DENIED_CODE = 18071;

type ApiStatusLike = {
    statusCode?: unknown;
    status_code?: unknown;
    code?: unknown;
    status?: unknown;
    data?: unknown;
    response?: {
        data?: unknown;
        status?: unknown;
    };
    message?: unknown;
    status_message?: unknown;
};

interface UseSpaceActionsOptions {
    activeSpaceId?: string;
    createdSortBy: SpaceSortType;
    joinedSortBy: SpaceSortType;
    departmentSortBy: SpaceSortType;
    createdSpaces: KnowledgeSpace[];
    joinedSpaces: KnowledgeSpace[];
    departmentSpaces: KnowledgeSpace[];
    onSpaceSelect: (space: KnowledgeSpace | null) => void;
}

function toStatusCode(value: unknown): number | null {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim()) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
}

function extractApiStatusCode(input: unknown): number | null {
    if (!input || typeof input !== "object") return null;

    const root = input as ApiStatusLike;
    const responseData = root.response?.data as ApiStatusLike | undefined;
    const data = root.data as ApiStatusLike | undefined;
    const candidates = [
        root.statusCode,
        root.status_code,
        root.code,
        responseData?.statusCode,
        responseData?.status_code,
        responseData?.code,
        data?.statusCode,
        data?.status_code,
        data?.code,
        root.response?.status,
        root.status,
    ];

    for (const candidate of candidates) {
        const code = toStatusCode(candidate);
        if (code != null) return code;
    }
    return null;
}

function createApiStatusError(input: unknown): Error & { statusCode?: number; status_code?: number } {
    const code = extractApiStatusCode(input);
    const root = (input && typeof input === "object" ? input : {}) as ApiStatusLike;
    const data = (root.response?.data || root.data || root) as ApiStatusLike;
    const message =
        typeof data.status_message === "string"
            ? data.status_message
            : typeof data.message === "string"
                ? data.message
                : `API request failed${code != null ? ` (${code})` : ""}`;
    const error = new Error(message) as Error & { statusCode?: number; status_code?: number };
    if (code != null) {
        error.statusCode = code;
        error.status_code = code;
    }
    return error;
}

function extractApiErrorMessage(input: unknown): string {
    const errorMessage = input instanceof Error ? input.message : "";
    if (!input || typeof input !== "object") return errorMessage;
    const root = input as {
        message?: unknown;
        status_message?: unknown;
        data?: { message?: unknown; status_message?: unknown };
        response?: { data?: { message?: unknown; status_message?: unknown } };
    };
    const candidates = [
        root.response?.data?.status_message,
        root.response?.data?.message,
        root.data?.status_message,
        root.data?.message,
        root.status_message,
        root.message,
        errorMessage,
    ];
    for (const candidate of candidates) {
        if (typeof candidate === "string" && candidate.trim()) return candidate;
    }
    return "";
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
        const previousJoined =
            queryClient.getQueryData<KnowledgeSpace[]>(["knowledgeSpaces", "joined", joinedSortBy])
            ?? joinedSpaces;
        const previousActive =
            previousJoined.find(s => s.id === spaceId)
            ?? joinedSpaces.find(s => s.id === spaceId)
            ?? null;
        const nextJoined = previousJoined.filter(s => s.id !== spaceId);
        const nextActive = nextJoined[0] ?? createdSpaces[0] ?? null;

        try {
            const response = await unsubscribeSpaceApi(spaceId);
            const exitCode = extractApiStatusCode(response);
            if (exitCode && exitCode !== 200) {
                throw createApiStatusError(response);
            }
            queryClient.setQueryData(["knowledgeSpaces", "joined", joinedSortBy], nextJoined);
            if (activeSpaceId === spaceId) {
                onSpaceSelect(nextActive);
            }
            queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces", "joined"] });
            showToast({ message: localize("com_knowledge.exited_space"), severity: NotificationSeverity.SUCCESS });
        } catch (e) {
            const errorCode = extractApiStatusCode(e);
            queryClient.setQueryData(["knowledgeSpaces", "joined", joinedSortBy], previousJoined);
            if (activeSpaceId === spaceId && previousActive) {
                onSpaceSelect(previousActive);
            }
            if (errorCode !== ORGANIZATION_GRANT_EXIT_DENIED_CODE) {
                queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces", "joined"] });
            }
            const message = errorCode === ORGANIZATION_GRANT_EXIT_DENIED_CODE
                ? localize("com_knowledge.organization_grant_exit_blocked")
                : extractApiErrorMessage(e) || localize("com_knowledge.exit_space_failed");
            showToast({ message, severity: NotificationSeverity.ERROR });
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
