import { useEffect, useMemo, useState } from "react";
import { Button } from "@bisheng/ui";

import type { BatchFileChangeApprovalResult } from "~/api/approval";
import type { FileChangeApprovalStatus, PendingUploadFileChange } from "~/api/knowledge";
import { Checkbox } from "~/components";
import { useLocalize } from "~/hooks";
import { formatBytes } from "~/utils";
import { cn } from "~/utils";

import { selectApprovablePendingUploads, summarizeBatchApprovalResult } from "../hooks/useFileChangeApproval";

interface PendingFileChangesPanelProps {
    items: PendingUploadFileChange[];
    loading?: boolean;
    statusFilter: FileChangeApprovalStatus[];
    onStatusFilterChange: (statuses: FileChangeApprovalStatus[]) => void;
    onOpenDetail: (requestId: number) => void;
    onPreview: (requestId: number) => void;
    onCleanup: (requestId: number) => void;
    onRetry: (requestId: number) => void;
    onBatchApprove: (requestIds: number[]) => void;
    batchApproving?: boolean;
    batchResult?: BatchFileChangeApprovalResult;
    hasMore?: boolean;
    fetchingMore?: boolean;
    onLoadMore?: () => void;
}

const FILTERS: FileChangeApprovalStatus[] = [
    "pending",
    "parsing",
    "parse_failed",
    "execute_failed",
];

function isRetryable(item: PendingUploadFileChange): boolean {
    return item.status === "parse_failed" || item.status === "execute_failed";
}

function isCleanable(item: PendingUploadFileChange): boolean {
    return [
        "pending", "approver_empty", "rejected", "withdrawn", "cancelled", "parse_failed", "execute_failed",
    ].includes(item.status);
}

export function PendingFileChangesPanel({
    items,
    loading = false,
    statusFilter,
    onStatusFilterChange,
    onOpenDetail,
    onPreview,
    onCleanup,
    onRetry,
    onBatchApprove,
    batchApproving = false,
    batchResult,
    hasMore = false,
    fetchingMore = false,
    onLoadMore,
}: PendingFileChangesPanelProps) {
    const localize = useLocalize();
    const [selected, setSelected] = useState<Set<number>>(new Set());
    const approvableIds = useMemo(
        () => new Set(selectApprovablePendingUploads(items).map((item) => item.requestId)),
        [items],
    );
    const selectedApprovable = Array.from(selected).filter((id) => approvableIds.has(id));
    const summary = batchResult ? summarizeBatchApprovalResult(batchResult) : undefined;

    useEffect(() => {
        const visibleIds = new Set(items.map((item) => item.requestId));
        setSelected((previous) => new Set(Array.from(previous).filter((id) => visibleIds.has(id))));
    }, [items]);

    const handleSelectAll = (checked: boolean) => {
        setSelected(checked ? approvableIds : new Set());
    };

    return (
        <section className="shrink-0 border-b border-border-base bg-background px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                    <h2 className="text-body font-medium text-text-1">
                        {localize("com_knowledge.file_change_pending_uploads")}
                    </h2>
                    <span className="text-caption text-text-3">{items.length}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Button
                        size="small"
                        variant={statusFilter.length === 0 ? "secondaryBrand" : "ghost"}
                        onClick={() => onStatusFilterChange([])}
                    >
                        {localize("com_knowledge.file_change_filter_all")}
                    </Button>
                    {FILTERS.map((status) => (
                        <Button
                            key={status}
                            size="small"
                            variant={statusFilter.includes(status) ? "secondaryBrand" : "ghost"}
                            onClick={() => onStatusFilterChange(
                                statusFilter.includes(status)
                                    ? statusFilter.filter((value) => value !== status)
                                    : [...statusFilter, status],
                            )}
                        >
                            {localize(`com_knowledge.file_change_status_${status}`)}
                        </Button>
                    ))}
                    {approvableIds.size > 0 && (
                        <Button
                            size="small"
                            loading={batchApproving}
                            disabled={selectedApprovable.length === 0}
                            onClick={() => onBatchApprove(selectedApprovable)}
                        >
                            {localize("com_knowledge.file_change_batch_approve")}
                        </Button>
                    )}
                </div>
            </div>

            {loading && <p className="py-3 text-body-sm text-text-3">{localize("com_approval_loading")}</p>}
            {!loading && items.length === 0 && (
                <p className="py-3 text-body-sm text-text-3">{localize("com_approval_empty_list")}</p>
            )}
            {!loading && items.length > 0 && (
                <div className="mt-3 max-h-56 overflow-y-auto rounded-lg border border-border-base">
                    <div className="grid grid-cols-[40px_minmax(180px,1fr)_100px_120px_minmax(230px,auto)] items-center bg-fill-2 px-3 py-2 text-caption text-text-3">
                        <Checkbox
                            checked={approvableIds.size > 0 && selectedApprovable.length === approvableIds.size}
                            onCheckedChange={(checked) => handleSelectAll(Boolean(checked))}
                        />
                        <span>{localize("com_knowledge.file_name")}</span>
                        <span>{localize("com_knowledge.file_size")}</span>
                        <span>{localize("com_knowledge.status")}</span>
                        <span>{localize("com_knowledge_operation")}</span>
                    </div>
                    {items.map((item) => (
                        <div
                            key={item.requestId}
                            className="grid grid-cols-[40px_minmax(180px,1fr)_100px_120px_minmax(230px,auto)] items-center border-t border-border-base px-3 py-2 text-body-sm"
                        >
                            <Checkbox
                                checked={selected.has(item.requestId)}
                                disabled={!approvableIds.has(item.requestId)}
                                onCheckedChange={(checked) => setSelected((previous) => {
                                    const next = new Set(previous);
                                    if (checked) next.add(item.requestId);
                                    else next.delete(item.requestId);
                                    return next;
                                })}
                            />
                            <button
                                type="button"
                                className="truncate text-left text-text-1 hover:text-blue-500"
                                onClick={() => onOpenDetail(item.requestId)}
                            >
                                {item.fileName}
                            </button>
                            <span className="text-text-2">{formatBytes(item.fileSize)}</span>
                            <span className={cn(
                                "w-fit rounded px-2 py-0.5 text-caption",
                                isRetryable(item) ? "bg-danger/10 text-danger" : "bg-blue-500/[0.07] text-blue-500",
                            )}>
                                {localize(`com_knowledge.file_change_status_${item.status}`)}
                            </span>
                            <div className="flex items-center gap-2">
                                <Button size="small" variant="ghost" onClick={() => onOpenDetail(item.requestId)}>
                                    {localize("com_knowledge.file_change_view_detail")}
                                </Button>
                                <Button size="small" variant="ghost" onClick={() => onPreview(item.requestId)}>
                                    {localize("com_knowledge.file_change_preview")}
                                </Button>
                                {isRetryable(item) && (
                                    <Button size="small" variant="ghost" onClick={() => onRetry(item.requestId)}>
                                        {localize("com_knowledge.retry")}
                                    </Button>
                                )}
                                {isCleanable(item) && (
                                    <Button size="small" color="danger" variant="ghost" onClick={() => onCleanup(item.requestId)}>
                                        {localize("com_knowledge.file_change_cleanup")}
                                    </Button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}
            {hasMore && onLoadMore && (
                <div className="mt-2 flex justify-center">
                    <Button size="small" variant="ghost" loading={fetchingMore} onClick={onLoadMore}>
                        {localize("com_show_more")}
                    </Button>
                </div>
            )}
            {summary && (
                <div className="mt-2 rounded-lg bg-fill-2 px-3 py-2 text-caption text-text-2">
                    <p>{localize("com_knowledge.file_change_batch_result", { 0: summary.successCount, 1: summary.failureCount })}</p>
                    {summary.failures.map((failure) => (
                        <p key={failure.requestId} className="text-danger">
                            #{failure.requestId} · {failure.latestStatus}
                            {failure.retryable ? ` · ${localize("com_knowledge.retry")}` : ""}
                            {failure.message ? ` · ${failure.message}` : ""}
                        </p>
                    ))}
                </div>
            )}
        </section>
    );
}
