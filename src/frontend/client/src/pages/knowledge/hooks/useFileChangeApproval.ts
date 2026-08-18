import { useCallback, useEffect, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
    batchApproveFileChangesApi,
    type BatchFileChangeApprovalResult,
} from "~/api/approval";
import {
    cleanupUploadFileChangeApi,
    decidePendingUploadFileChangeApi,
    getFileChangeDetailApi,
    listPendingUploadFileChangesApi,
    retryFileChangeIngestApi,
    type FileChangeApprovalStatus,
    type FileChangeDetail,
    type KnowledgeFile,
    type PendingUploadFileChange,
} from "~/api/knowledge";
import { getFileTypeFromName } from "../knowledgeUtils";

import { FILE_CHANGE_APPROVAL_REFRESH_EVENT } from "~/events/fileChangeApprovalEvents";

export interface FileChangeLockState {
    locked: boolean;
    showBadge: boolean;
    requestId?: number;
}

export interface FileChangeActionRow {
    key: "oldName" | "newName" | "sourcePath" | "targetPath" | "resourceName" | "failureReason";
    value: string;
}

export interface BatchApprovalSummary {
    successCount: number;
    failureCount: number;
    failures: Array<{
        requestId: number;
        latestStatus: string;
        retryable: boolean;
        message?: string;
    }>;
}

/** Merge a partial refreshed page while treating an omitted approval field as hidden/cleared. */
export function mergeFileChangeApprovalEnrichment(
    current: KnowledgeFile[],
    incoming: KnowledgeFile[],
): KnowledgeFile[] {
    const incomingById = new Map(incoming.map((file) => [file.id, file]));
    return current.map((file) => {
        const refreshed = incomingById.get(file.id);
        if (!refreshed) return file;
        return { ...file, fileChangeApproval: refreshed.fileChangeApproval };
    });
}

export function getFileChangeLockState(file: KnowledgeFile): FileChangeLockState {
    const approval = file.fileChangeApproval;
    if (!approval) return { locked: false, showBadge: false };
    return {
        locked: true,
        showBadge: !approval.inherited,
        requestId: approval.requestId,
    };
}

export function selectApprovablePendingUploads(
    items: PendingUploadFileChange[],
): PendingUploadFileChange[] {
    return items.filter(canDecidePendingUpload);
}

/** Terminal uploads are not pending rows: applied files are formal, while closed uploads never succeeded. */
export function selectVisiblePendingUploads(
    items: PendingUploadFileChange[],
): PendingUploadFileChange[] {
    return items.filter((item) => item.status !== "applied" && item.status !== "closed");
}

/**
 * Execution states a decided upload passes through before its formal file
 * exists. The backend advances these on its own (queued → applying → applied),
 * so the pending list must be polled while any row sits here — otherwise an
 * approved upload stays visually stuck on 等待执行 / 处理中 until a manual refresh.
 */
export const FILE_CHANGE_IN_FLIGHT_STATUSES: FileChangeApprovalStatus[] = [
    "queued",
    "applying",
    "compensating",
];

/** Poll cadence (ms) for refreshing in-flight pending-upload rows. */
export const PENDING_UPLOAD_POLL_INTERVAL_MS = 5000;

/**
 * True while a decided upload is still executing (queued / applying /
 * compensating). Undecided rows (approvalStatus === "pending") are excluded:
 * their `status` only becomes meaningful after a decision and they never move
 * without a human action, so polling them would spin forever.
 */
export function isPendingUploadInFlight(item: PendingUploadFileChange): boolean {
    return item.approvalStatus !== "pending"
        && FILE_CHANGE_IN_FLIGHT_STATUSES.includes(item.status);
}

export function canDecidePendingUpload(item?: PendingUploadFileChange): boolean {
    return Boolean(item?.approvalStatus === "pending" && item.canApprove);
}

/**
 * True when the current viewer is the applicant of this still-pending upload.
 *
 * Compares the row's applicant id against the current user id directly. The
 * earlier `!canApprove` heuristic only held under the backend list-filter
 * invariant (non-managers list only their own uploads); a direct ownership
 * check stays correct even if that invariant changes (e.g. an auditor role that
 * can list uploads it did not create). Withdraw is applicant-only on the
 * backend, so this must match that guard.
 */
export function canWithdrawPendingUpload(
    item: PendingUploadFileChange | undefined,
    currentUserId: string | number | undefined,
): boolean {
    return Boolean(
        item?.approvalStatus === "pending" &&
        currentUserId != null &&
        String(item.applicantUserId) === String(currentUserId),
    );
}

/**
 * Whether a pending-upload projection row may be ticked in the file list.
 *
 * Only rows whose approval is still pending are selectable — the applicant can
 * batch-withdraw them and an approver can batch-decide them. Once the approval
 * is decided the row moves into an execution state (queued / applying / failed /
 * compensating); those rows carry no batch semantics (their retry / cleanup are
 * per-row, applicant-only actions in the detail sheet), so they keep a disabled
 * checkbox rather than becoming a dead selection. Mirrored by `isSelectable` in
 * FileListRow / FileCard and `isSelectableFile` in the page container.
 */
export function isPendingUploadSelectable(item?: PendingUploadFileChange): boolean {
    return item?.approvalStatus === "pending";
}

export function projectPendingUploadAsKnowledgeFile(
    item: PendingUploadFileChange,
    spaceId: string,
): KnowledgeFile {
    const timestamp = item.updateTime ?? item.createTime ?? "";
    return {
        id: `pending-upload:${item.requestId}`,
        name: item.fileName,
        type: getFileTypeFromName(item.fileName),
        size: item.fileSize,
        tags: [],
        path: "",
        parentId: item.parentId == null ? undefined : String(item.parentId),
        spaceId,
        createdAt: item.createTime ?? timestamp,
        updatedAt: timestamp,
        pendingUploadApproval: item,
    };
}

export function buildFileChangeActionRows(detail: FileChangeDetail): FileChangeActionRow[] {
    const rows: FileChangeActionRow[] = [];
    if (detail.action === "rename") {
        if (detail.actionDetail.oldName) rows.push({ key: "oldName", value: detail.actionDetail.oldName });
        if (detail.actionDetail.newName) rows.push({ key: "newName", value: detail.actionDetail.newName });
    } else if (detail.action === "move") {
        if (detail.actionDetail.sourcePath) rows.push({ key: "sourcePath", value: detail.actionDetail.sourcePath });
        if (detail.actionDetail.targetPath) rows.push({ key: "targetPath", value: detail.actionDetail.targetPath });
    } else {
        rows.push({ key: "resourceName", value: detail.resourceName });
    }
    if (detail.failureReason) rows.push({ key: "failureReason", value: detail.failureReason });
    return rows;
}

export function summarizeBatchApprovalResult(
    result: BatchFileChangeApprovalResult,
): BatchApprovalSummary {
    return {
        successCount: result.successCount,
        failureCount: result.failureCount,
        failures: result.items
            .filter((item) => item.result !== "approved")
            .map((item) => ({
                requestId: item.changeRequestId,
                latestStatus: item.latestStatus,
                retryable: item.retryable,
                message: item.errorMessage,
            })),
    };
}

interface UseFileChangeApprovalOptions {
    spaceId?: string;
    parentId?: string;
    enabled?: boolean;
    onFormalFilesRefresh?: () => void | Promise<void>;
}

export function useFileChangeApproval({
    spaceId,
    parentId,
    enabled = true,
    onFormalFilesRefresh,
}: UseFileChangeApprovalOptions) {
    const queryClient = useQueryClient();
    const [detailRequestId, setDetailRequestId] = useState<number | null>(null);
    const pendingQueryKey = ["knowledge-file-change-uploads", spaceId, parentId ?? null] as const;

    const pendingQuery = useInfiniteQuery({
        queryKey: pendingQueryKey,
        queryFn: ({ pageParam }) => listPendingUploadFileChangesApi(spaceId!, {
            parentId,
            cursor: pageParam,
            pageSize: 100,
        }),
        getNextPageParam: (lastPage) => lastPage.hasMore ? lastPage.nextCursor : undefined,
        enabled: enabled && Boolean(spaceId),
        // Auto-refresh while any decided upload is still executing (等待执行 /
        // 处理中). The backend advances these states asynchronously with no push
        // channel, so without polling the row would freeze until a manual
        // reload. Reads live query data (not a render-time closure) so the
        // interval turns itself off the moment every row reaches a terminal
        // state.
        refetchInterval: (data) => {
            const items = data?.pages.flatMap((page) => page.data) ?? [];
            return items.some(isPendingUploadInFlight) ? PENDING_UPLOAD_POLL_INTERVAL_MS : false;
        },
    });
    const detailQuery = useQuery({
        queryKey: ["knowledge-file-change-detail", spaceId, detailRequestId],
        queryFn: () => getFileChangeDetailApi(spaceId!, detailRequestId!),
        enabled: enabled && Boolean(spaceId) && detailRequestId != null,
    });

    const pendingItems = pendingQuery.data?.pages.flatMap((page) => page.data) ?? [];

    // When a polled row transitions into the terminal "applied" state its formal
    // file has just been created, and the pending projection stops rendering it
    // (selectVisiblePendingUploads drops "applied"). Pull the real file list so
    // the file reappears as a formal row instead of vanishing from the view.
    const seenStatusRef = useRef<Map<number, FileChangeApprovalStatus>>(new Map());
    const initializedRef = useRef(false);
    useEffect(() => {
        const previous = seenStatusRef.current;
        const next = new Map<number, FileChangeApprovalStatus>();
        let sawCompletion = false;
        for (const item of pendingItems) {
            next.set(item.requestId, item.status);
            const before = previous.get(item.requestId);
            if (before && before !== "applied" && item.status === "applied") {
                sawCompletion = true;
            }
        }
        seenStatusRef.current = next;
        // Skip the first snapshot: pre-existing applied rows are history, not a
        // transition we just observed.
        if (initializedRef.current && sawCompletion) {
            void onFormalFilesRefresh?.();
        }
        initializedRef.current = true;
    }, [pendingItems, onFormalFilesRefresh]);

    const refreshAll = useCallback(async () => {
        await queryClient.invalidateQueries({ queryKey: ["knowledge-file-change-uploads", spaceId] });
        if (detailRequestId != null) {
            await queryClient.invalidateQueries({
                queryKey: ["knowledge-file-change-detail", spaceId, detailRequestId],
            });
        }
        await onFormalFilesRefresh?.();
    }, [detailRequestId, onFormalFilesRefresh, queryClient, spaceId]);

    useEffect(() => {
        const handleRefresh = (event: Event) => {
            const eventSpaceId = (event as CustomEvent<{ spaceId?: string | number }>).detail?.spaceId;
            if (eventSpaceId != null && String(eventSpaceId) !== String(spaceId)) return;
            void refreshAll();
        };
        window.addEventListener(FILE_CHANGE_APPROVAL_REFRESH_EVENT, handleRefresh);
        return () => window.removeEventListener(FILE_CHANGE_APPROVAL_REFRESH_EVENT, handleRefresh);
    }, [refreshAll, spaceId]);

    const batchApproveMutation = useMutation({
        mutationFn: (changeRequestIds: number[]) => batchApproveFileChangesApi(spaceId!, {
            change_request_ids: changeRequestIds,
        }),
        onSettled: refreshAll,
    });
    const retryMutation = useMutation({
        mutationFn: (requestId: number) => retryFileChangeIngestApi(spaceId!, requestId),
        onSettled: refreshAll,
    });
    const cleanupMutation = useMutation({
        mutationFn: (requestId: number) => cleanupUploadFileChangeApi(spaceId!, requestId),
        onSettled: refreshAll,
    });
    const decisionMutation = useMutation({
        mutationFn: ({ requestId, action }: { requestId: number; action: "approve" | "reject" }) =>
            decidePendingUploadFileChangeApi(spaceId!, requestId, action),
        onSettled: refreshAll,
    });

    const closeDetail = useCallback(() => setDetailRequestId(null), []);
    const refreshFormalFiles = useCallback(() => {
        if (spaceId) {
            window.dispatchEvent(new CustomEvent("knowledge-space-files:refresh", {
                detail: { spaceId },
            }));
        }
    }, [spaceId]);

    return {
        pendingItems,
        pendingLoading: pendingQuery.isLoading,
        pendingHasMore: pendingQuery.hasNextPage,
        pendingFetchingMore: pendingQuery.isFetchingNextPage,
        fetchPendingNextPage: pendingQuery.fetchNextPage,
        refreshAll,
        refreshFormalFiles,
        detailRequestId,
        openDetail: setDetailRequestId,
        closeDetail,
        detail: detailQuery.data,
        detailLoading: detailQuery.isLoading,
        retryIngest: retryMutation.mutateAsync,
        retrying: retryMutation.isPending,
        cleanup: cleanupMutation.mutateAsync,
        cleaning: cleanupMutation.isPending,
        batchApprove: batchApproveMutation.mutateAsync,
        batchApproving: batchApproveMutation.isPending,
        batchApprovalResult: batchApproveMutation.data,
        decide: decisionMutation.mutateAsync,
        deciding: decisionMutation.isPending,
    };
}
