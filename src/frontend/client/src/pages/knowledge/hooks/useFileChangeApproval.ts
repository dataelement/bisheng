import { useCallback, useEffect, useState } from "react";
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
    return items.filter((item) => item.status === "pending" && item.canApprove);
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
    });
    const detailQuery = useQuery({
        queryKey: ["knowledge-file-change-detail", spaceId, detailRequestId],
        queryFn: () => getFileChangeDetailApi(spaceId!, detailRequestId!),
        enabled: enabled && Boolean(spaceId) && detailRequestId != null,
    });

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
        pendingItems: pendingQuery.data?.pages.flatMap((page) => page.data) ?? [],
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
