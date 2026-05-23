import { useQueryClient, useQuery, useMutation } from "@tanstack/react-query";
import { CheckCircle, Download, Eye, Loader2, Trash2, X } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "~/components/ui/Dialog";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { Button } from "~/components/ui/Button";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { useConfirm } from "~/Providers";
import {
    FileStatus,
    FileVersionEntry,
    getFileVersionsApi,
    setPrimaryVersionApi,
    deleteFileVersionApi,
} from "~/api/knowledge";
import { cn } from "~/utils";

// ─── Props ────────────────────────────────────────────────────────────────────

interface VersionHistoryDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** knowledge_file_id of the current primary version; null when closed */
    fileId: number | null;
    /** Shown in the dialog header for context (falls back to API response title) */
    documentTitle?: string;
    /** User has owner/manager role on this space */
    canManage: boolean;
    onPreview?: (versionFileId: number, fileName: string) => void;
    onDownload?: (versionFileId: number, fileName: string) => void;
    onPrimaryChanged?: () => void;
    onDeleted?: () => void;
}

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
    string,
    { labelKey: string; color: string; bg: string; dot: string }
> = {
    [FileStatus.SUCCESS]: {
        labelKey: "com_knowledge.success",
        color: "text-[#00b42a]",
        bg: "bg-[#e8ffea]",
        dot: "bg-[#00b42a]",
    },
    [FileStatus.PROCESSING]: {
        labelKey: "com_knowledge.parsing_status",
        color: "text-[#165dff]",
        bg: "bg-[#e8f3ff]",
        dot: "bg-[#165dff]",
    },
    [FileStatus.WAITING]: {
        labelKey: "com_knowledge.queueing_status",
        color: "text-[#165dff]",
        bg: "bg-[#e8f3ff]",
        dot: "bg-[#165dff]",
    },
    [FileStatus.REBUILDING]: {
        labelKey: "com_knowledge.rebuilding_status",
        color: "text-[#165dff]",
        bg: "bg-[#e8f3ff]",
        dot: "bg-[#165dff]",
    },
    [FileStatus.UPLOADING]: {
        labelKey: "com_knowledge.uploading_status",
        color: "text-[#165dff]",
        bg: "bg-[#e8f3ff]",
        dot: "bg-[#165dff]",
    },
    [FileStatus.FAILED]: {
        labelKey: "com_knowledge.fail",
        color: "text-[#f53f3f]",
        bg: "bg-[#fff2f0]",
        dot: "bg-[#f53f3f]",
    },
    [FileStatus.TIMEOUT]: {
        labelKey: "com_knowledge.timeout",
        color: "text-[#f53f3f]",
        bg: "bg-[#fff2f0]",
        dot: "bg-[#f53f3f]",
    },
    [FileStatus.VIOLATION]: {
        labelKey: "com_knowledge.violation",
        color: "text-[#f53f3f]",
        bg: "bg-[#fff2f0]",
        dot: "bg-[#f53f3f]",
    },
};

function numericStatusToEnum(n: number): FileStatus {
    switch (n) {
        case 1: return FileStatus.PROCESSING;
        case 2: return FileStatus.SUCCESS;
        case 3: return FileStatus.FAILED;
        case 4: return FileStatus.REBUILDING;
        case 5: return FileStatus.WAITING;
        case 6: return FileStatus.TIMEOUT;
        case 7: return FileStatus.VIOLATION;
        default: return FileStatus.WAITING;
    }
}

interface VersionStatusBadgeProps {
    parseStatus: number;
}

function VersionStatusBadge({ parseStatus }: VersionStatusBadgeProps) {
    const localize = useLocalize();
    const status = numericStatusToEnum(parseStatus);
    const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG[FileStatus.WAITING];
    return (
        <span
            className={cn(
                "inline-flex shrink-0 items-center whitespace-nowrap rounded px-2 py-0.5 text-xs",
                cfg.bg,
                cfg.color,
            )}
        >
            {localize(cfg.labelKey)}
        </span>
    );
}

// ─── Action button with tooltip ───────────────────────────────────────────────

interface ActionButtonProps {
    label: string;
    onClick: () => void;
    disabled?: boolean;
    className?: string;
    children: React.ReactNode;
}

function ActionButton({ label, onClick, disabled, className, children }: ActionButtonProps) {
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <button
                    type="button"
                    disabled={disabled}
                    onClick={onClick}
                    className={cn(
                        "inline-flex size-7 items-center justify-center rounded-[4px] border border-[#ECECEC] bg-white text-[#4e5969]",
                        "transition-colors hover:bg-[#f7f7f7] disabled:cursor-not-allowed disabled:opacity-40",
                        className,
                    )}
                >
                    {children}
                </button>
            </TooltipTrigger>
            <TooltipContent
                noArrow
                side="top"
                className="z-[200] rounded-md bg-[#1D2129] px-2 py-1 text-xs text-white"
            >
                {label}
            </TooltipContent>
        </Tooltip>
    );
}

// ─── Table row ────────────────────────────────────────────────────────────────

interface VersionTableRowProps {
    version: FileVersionEntry;
    canManage: boolean;
    setPrimaryPending: boolean;
    deletePending: boolean;
    onPreview?: (versionFileId: number, fileName: string) => void;
    onDownload?: (versionFileId: number, fileName: string) => void;
    onSetPrimary: (versionId: number, versionNo: number) => void;
    onDelete: (versionId: number, versionNo: number) => void;
}

function VersionTableRow({
    version,
    canManage,
    setPrimaryPending,
    deletePending,
    onPreview,
    onDownload,
    onSetPrimary,
    onDelete,
}: VersionTableRowProps) {
    const localize = useLocalize();
    const isSuccess = numericStatusToEnum(version.status ?? 0) === FileStatus.SUCCESS;
    const canSetPrimary = canManage && !version.is_primary && isSuccess;
    const canDelete = canManage && !version.is_primary;
    const anyPending = setPrimaryPending || deletePending;

    return (
        <tr className="border-b border-[#F2F3F5] last:border-b-0 hover:bg-[#FAFAFA]">
            {/* Version */}
            <td className="px-4 py-3 text-sm text-[#1d2129] whitespace-nowrap">
                <div className="flex items-center gap-2">
                    <span className="font-medium">V{version.version_no}</span>
                    {version.is_primary && (
                        <span className="inline-flex items-center rounded bg-[#E8F3FF] px-1.5 py-0.5 text-[11px] font-medium text-[#165DFF]">
                            {localize("com_knowledge.version.history_primary_badge")}
                        </span>
                    )}
                </div>
            </td>

            {/* Original file name */}
            <td className="max-w-[200px] px-4 py-3">
                <span className="block truncate text-sm text-[#1d2129]" title={version.original_file_name}>
                    {version.original_file_name}
                </span>
            </td>

            {/* File encoding (doc_code per version) */}
            <td className="max-w-[180px] px-4 py-3">
                <span className="block truncate text-sm text-[#4e5969]" title={version.file_code ?? undefined}>
                    {version.file_code ?? "—"}
                </span>
            </td>

            {/* Uploader */}
            <td className="px-4 py-3 text-sm text-[#4e5969] whitespace-nowrap">
                {version.uploader_name ?? "—"}
            </td>

            {/* Upload time */}
            <td className="px-4 py-3 text-sm text-[#4e5969] whitespace-nowrap">
                {version.upload_time ? version.upload_time.replace("T", " ").slice(0, 16) : "—"}
            </td>

            {/* Status */}
            <td className="px-4 py-3">
                <VersionStatusBadge parseStatus={version.status ?? 0} />
            </td>

            {/* Actions */}
            <td className="px-4 py-3">
                <div className="flex items-center gap-1.5">
                    {onPreview && (
                        <ActionButton
                            label={localize("com_knowledge.version.history_action_preview")}
                            onClick={() => onPreview(version.knowledge_file_id, version.original_file_name)}
                            disabled={anyPending}
                        >
                            <Eye className="size-4" />
                        </ActionButton>
                    )}
                    {onDownload && (
                        <ActionButton
                            label={localize("com_knowledge.version.history_action_download")}
                            onClick={() => onDownload(version.knowledge_file_id, version.original_file_name)}
                            disabled={anyPending}
                        >
                            <Download className="size-4" />
                        </ActionButton>
                    )}
                    {canSetPrimary && (
                        <ActionButton
                            label={localize("com_knowledge.version.history_action_set_primary")}
                            onClick={() => onSetPrimary(version.version_id, version.version_no)}
                            disabled={anyPending}
                            className="text-[#165dff] hover:text-[#165dff]"
                        >
                            <CheckCircle className="size-4" />
                        </ActionButton>
                    )}
                    {canDelete && (
                        <ActionButton
                            label={localize("com_knowledge.version.history_action_delete")}
                            onClick={() => onDelete(version.version_id, version.version_no)}
                            disabled={anyPending}
                            className="hover:text-[#f53f3f]"
                        >
                            <Trash2 className="size-4" />
                        </ActionButton>
                    )}
                </div>
            </td>
        </tr>
    );
}

// ─── Top info panel (3-column summary) ────────────────────────────────────────

interface InfoColumnProps {
    label: string;
    value: string | null | undefined;
}

function InfoColumn({ label, value }: InfoColumnProps) {
    return (
        <div className="flex-1 min-w-0">
            <p className="text-xs text-[#86909c] mb-1">{label}</p>
            <p className="truncate text-sm font-medium text-[#1d2129]" title={value ?? undefined}>
                {value ?? "—"}
            </p>
        </div>
    );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function VersionHistorySheet({
    open,
    onOpenChange,
    fileId,
    documentTitle,
    canManage,
    onPreview,
    onDownload,
    onPrimaryChanged,
    onDeleted,
}: VersionHistoryDialogProps): JSX.Element | null {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const queryClient = useQueryClient();

    const { data, isLoading } = useQuery({
        queryKey: ["file-versions", fileId],
        queryFn: () => getFileVersionsApi(fileId!),
        enabled: open && fileId !== null,
    });
    const versions = data?.versions ?? [];
    const sortedVersions = [...versions].sort((a, b) => a.version_no - b.version_no);
    const headerTitle = data?.title ?? documentTitle ?? "";
    const docCode = data?.doc_code ?? null;
    const primaryVersionNo = data?.current_primary_version_no ?? null;

    const setPrimaryMutation = useMutation({
        mutationFn: (versionId: number) => setPrimaryVersionApi(versionId),
        onSuccess: () => {
            showToast({
                message: localize("com_knowledge.version.toast_set_primary_success"),
                status: "success",
            });
            queryClient.invalidateQueries({ queryKey: ["file-versions", fileId] });
            onPrimaryChanged?.();
        },
        onError: () => {
            showToast({
                message: localize("com_knowledge.version.toast_set_primary_failure"),
                status: "error",
            });
        },
    });

    const deleteMutation = useMutation({
        mutationFn: (versionId: number) => deleteFileVersionApi(versionId),
        onSuccess: () => {
            showToast({
                message: localize("com_knowledge.version.toast_delete_success"),
                status: "success",
            });
            queryClient.invalidateQueries({ queryKey: ["file-versions", fileId] });
            onDeleted?.();
        },
        onError: () => {
            showToast({
                message: localize("com_knowledge.version.toast_delete_failure"),
                status: "error",
            });
        },
    });

    const handleSetPrimary = async (versionId: number, versionNo: number) => {
        const ok = await confirm({
            title: localize("com_knowledge.version.history_confirm_set_primary_title"),
            description: localize(
                "com_knowledge.version.history_confirm_set_primary_description",
                { version: String(versionNo) },
            ),
        });
        if (!ok) return;
        setPrimaryMutation.mutate(versionId);
    };

    const handleDelete = async (versionId: number, versionNo: number) => {
        const ok = await confirm({
            title: localize("com_knowledge.version.history_confirm_delete_title"),
            description: localize(
                "com_knowledge.version.history_confirm_delete_description",
                { version: String(versionNo) },
            ),
        });
        if (!ok) return;
        deleteMutation.mutate(versionId);
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                className="flex max-h-[80vh] w-[860px] max-w-[90vw] flex-col gap-0 overflow-hidden rounded-xl p-0 sm:max-w-[860px] [&>button]:hidden"
            >
                {/* Header */}
                <DialogHeader className="relative shrink-0 px-6 pt-5 pb-3 text-left">
                    <DialogTitle className="text-base font-semibold text-[#1d2129]">
                        {localize("com_knowledge.version.history_title")}
                    </DialogTitle>
                    <button
                        type="button"
                        onClick={() => onOpenChange(false)}
                        className="absolute right-4 top-4 inline-flex size-8 items-center justify-center rounded-md text-[#4E5969] transition-colors hover:bg-[#F2F3F5]"
                        aria-label={localize("com_knowledge.close") || "Close"}
                    >
                        <X className="size-4" />
                    </button>
                </DialogHeader>

                {/* Body */}
                <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4">
                    {/* 3-column info panel */}
                    <div className="mb-4 flex gap-6 rounded-[8px] border border-[#EBECF0] bg-[#F7F8FA] px-4 py-3">
                        <InfoColumn
                            label={localize("com_knowledge.version.history_label_doc")}
                            value={headerTitle}
                        />
                        <InfoColumn
                            label={localize("com_knowledge.version.history_label_doc_code")}
                            value={docCode}
                        />
                        <InfoColumn
                            label={localize("com_knowledge.version.history_label_primary_version")}
                            value={primaryVersionNo != null ? `V${primaryVersionNo}` : null}
                        />
                    </div>

                    {/* Table */}
                    {isLoading ? (
                        <div className="flex h-32 items-center justify-center">
                            <Loader2 className="size-6 animate-spin text-[#86909c]" />
                        </div>
                    ) : sortedVersions.length === 0 ? (
                        <div className="flex h-32 items-center justify-center text-sm text-[#86909c]">
                            —
                        </div>
                    ) : (
                        <div className="overflow-x-auto rounded-[8px] border border-[#EBECF0]">
                            <table className="w-full min-w-[720px] border-collapse text-sm">
                                <thead>
                                    <tr className="border-b border-[#EBECF0] bg-[#FAFAFA]">
                                        <th className="px-4 py-2.5 text-left text-xs font-medium text-[#86909c]">
                                            {localize("com_knowledge.version.history_col_version")}
                                        </th>
                                        <th className="px-4 py-2.5 text-left text-xs font-medium text-[#86909c]">
                                            {localize("com_knowledge.version.history_col_filename")}
                                        </th>
                                        <th className="px-4 py-2.5 text-left text-xs font-medium text-[#86909c]">
                                            {localize("com_knowledge.version.history_col_file_encoding")}
                                        </th>
                                        <th className="px-4 py-2.5 text-left text-xs font-medium text-[#86909c]">
                                            {localize("com_knowledge.version.history_col_uploader")}
                                        </th>
                                        <th className="px-4 py-2.5 text-left text-xs font-medium text-[#86909c]">
                                            {localize("com_knowledge.version.history_col_upload_time")}
                                        </th>
                                        <th className="px-4 py-2.5 text-left text-xs font-medium text-[#86909c]">
                                            {localize("com_knowledge.version.history_col_parse_status")}
                                        </th>
                                        <th className="px-4 py-2.5 text-left text-xs font-medium text-[#86909c]">
                                            {localize("com_knowledge.version.history_col_actions")}
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {sortedVersions.map((v) => (
                                        <VersionTableRow
                                            key={v.version_id}
                                            version={v}
                                            canManage={canManage}
                                            setPrimaryPending={setPrimaryMutation.isPending}
                                            deletePending={deleteMutation.isPending}
                                            onPreview={onPreview}
                                            onDownload={onDownload}
                                            onSetPrimary={handleSetPrimary}
                                            onDelete={handleDelete}
                                        />
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="shrink-0 flex justify-end gap-2 border-t border-[#e5e6eb] px-6 py-3">
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                    >
                        {localize("com_knowledge.version.btn_close")}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
