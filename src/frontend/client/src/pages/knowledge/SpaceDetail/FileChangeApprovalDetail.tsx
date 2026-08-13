import type { BatchFileChangeApprovalResult } from "~/api/approval";
import type { FileChangeDetail } from "~/api/knowledge";
import { Button } from "@bisheng/ui";
import {
    Sheet,
    SheetContent,
    SheetFooter,
    SheetHeader,
    SheetTitle,
} from "~/components/ui/Sheet";
import { useLocalize } from "~/hooks";

import { buildFileChangeActionRows, summarizeBatchApprovalResult } from "../hooks/useFileChangeApproval";

interface FileChangeApprovalDetailProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    detail?: FileChangeDetail;
    loading?: boolean;
    approving?: boolean;
    batchResult?: BatchFileChangeApprovalResult;
    onApprove?: (requestId: number) => void;
    onPreview?: (requestId: number) => void;
    onRetry?: (requestId: number) => void;
    onCleanup?: (requestId: number) => void;
}

const rowLabelKeys = {
    oldName: "com_knowledge.file_change_old_name",
    newName: "com_knowledge.file_change_new_name",
    sourcePath: "com_knowledge.file_change_source_path",
    targetPath: "com_knowledge.file_change_target_path",
    resourceName: "com_knowledge.file_name",
    failureReason: "com_knowledge.file_change_failure_reason",
} as const;

function canRetry(detail: FileChangeDetail): boolean {
    return detail.action === "upload" && detail.status === "failed";
}

function canCleanup(detail: FileChangeDetail): boolean {
    return detail.action === "upload" && detail.status === "failed";
}

export function FileChangeApprovalDetail({
    open,
    onOpenChange,
    detail,
    loading = false,
    approving = false,
    batchResult,
    onApprove,
    onPreview,
    onRetry,
    onCleanup,
}: FileChangeApprovalDetailProps) {
    const localize = useLocalize();
    const rows = detail ? buildFileChangeActionRows(detail) : [];
    const batchSummary = batchResult ? summarizeBatchApprovalResult(batchResult) : undefined;

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="w-full sm:max-w-[480px]">
                <SheetHeader className="border-b border-border-base">
                    <SheetTitle>{localize("com_knowledge.file_change_detail_title")}</SheetTitle>
                </SheetHeader>
                <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
                    {loading && <p className="text-body-sm text-text-3">{localize("com_approval_loading")}</p>}
                    {!loading && !detail && (
                        <p className="text-body-sm text-text-3">{localize("com_approval_empty_detail")}</p>
                    )}
                    {detail && (
                        <div className="space-y-5">
                            <section className="space-y-3">
                                <h3 className="text-body font-medium text-text-1">
                                    {localize("com_approval_section_basic_info")}
                                </h3>
                                <DetailRow label={localize("com_knowledge.file_name")} value={detail.resourceName} />
                                <DetailRow label={localize("com_knowledge.file_change_action")} value={localize(`com_knowledge.file_change_action_${detail.action}`)} />
                                <DetailRow
                                    label={localize("com_knowledge.file_change_business_status")}
                                    value={localize(`com_knowledge.file_change_status_${detail.status}`)}
                                />
                                {detail.approvalStatus && (
                                    <DetailRow
                                        label={localize("com_approval_status_label")}
                                        value={localize(`com_approval_status_${detail.approvalStatus}`)}
                                    />
                                )}
                                <DetailRow label={localize("com_approval_field_applicant")} value={detail.applicantUserName || String(detail.applicantUserId)} />
                            </section>
                            <section className="space-y-3">
                                <h3 className="text-body font-medium text-text-1">
                                    {localize("com_approval_section_business_content")}
                                </h3>
                                {rows.map((row) => (
                                    <DetailRow key={row.key} label={localize(rowLabelKeys[row.key])} value={row.value} />
                                ))}
                            </section>
                            {batchSummary && (
                                <section className="space-y-2 rounded-lg bg-fill-2 p-3">
                                    <p className="text-body-sm text-text-1">
                                        {localize("com_knowledge.file_change_batch_result", {
                                            0: batchSummary.successCount,
                                            1: batchSummary.failureCount,
                                        })}
                                    </p>
                                    {batchSummary.failures.map((failure) => (
                                        <p key={failure.requestId} className="text-caption text-danger">
                                            #{failure.requestId} · {failure.latestStatus}
                                            {failure.retryable ? ` · ${localize("com_knowledge.retry")}` : ""}
                                            {failure.message ? ` · ${failure.message}` : ""}
                                        </p>
                                    ))}
                                </section>
                            )}
                        </div>
                    )}
                </div>
                {detail && (
                    <SheetFooter className="flex-row justify-end border-t border-border-base">
                        {detail.action === "upload" && onPreview && (
                            <Button variant="outline" onClick={() => onPreview(detail.requestId)}>
                                {localize("com_knowledge.file_change_preview")}
                            </Button>
                        )}
                        {canCleanup(detail) && onCleanup && (
                            <Button color="danger" variant="outline" onClick={() => onCleanup(detail.requestId)}>
                                {localize("com_knowledge.file_change_cleanup")}
                            </Button>
                        )}
                        {canRetry(detail) && onRetry && (
                            <Button variant="outline" onClick={() => onRetry(detail.requestId)}>
                                {localize("com_knowledge.retry")}
                            </Button>
                        )}
                        {detail.canApprove && detail.approvalStatus === "pending" && onApprove && (
                            <Button loading={approving} onClick={() => onApprove(detail.requestId)}>
                                {localize("com_approval_action_approve")}
                            </Button>
                        )}
                    </SheetFooter>
                )}
            </SheetContent>
        </Sheet>
    );
}

function DetailRow({ label, value }: { label: string; value: string }) {
    return (
        <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-3 text-body-sm">
            <span className="text-text-3">{label}</span>
            <span className="break-words text-text-1">{value}</span>
        </div>
    );
}
