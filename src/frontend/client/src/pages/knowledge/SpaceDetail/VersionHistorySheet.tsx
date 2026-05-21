import { useQueryClient, useQuery, useMutation } from "@tanstack/react-query";
import { CheckCircle, Download, Eye, Loader2, Trash2 } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "~/components/ui/Sheet";
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

interface VersionHistorySheetProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** knowledge_file_id of the current primary version; null when closed */
    fileId: number | null;
    /** Shown in the sheet header for context */
    documentTitle?: string;
    /** User has owner/manager role on this space */
    canManage: boolean;
    onPreview?: (versionFileId: number) => void;
    onDownload?: (versionFileId: number) => void;
    onPrimaryChanged?: () => void;
    onDeleted?: () => void;
}

// ─── Status badge ─────────────────────────────────────────────────────────────

// mirrors FileTable StatusBadge — extract when used 3+ times
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

/** Map backend numeric parse_status to FileStatus enum string */
function numericStatusToEnum(n: number): FileStatus {
    // fileStatusToNumber reverse map; default to WAITING for unknown
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
        <div
            className={cn(
                "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm px-2 py-0.5 text-xs font-medium",
                cfg.bg,
                cfg.color,
            )}
        >
            <span className={cn("size-1.5 shrink-0 rounded-full", cfg.dot)} />
            {localize(cfg.labelKey)}
        </div>
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
                className="rounded-md bg-[#1D2129] px-2 py-1 text-xs text-white"
            >
                {label}
            </TooltipContent>
        </Tooltip>
    );
}

// ─── Table row sub-component ──────────────────────────────────────────────────

interface VersionTableRowProps {
    version: FileVersionEntry;
    canManage: boolean;
    setPrimaryPending: boolean;
    deletePending: boolean;
    onPreview?: (versionFileId: number) => void;
    onDownload?: (versionFileId: number) => void;
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
        <tr className="border-b border-[#e5e6eb] hover:bg-[#f7f7f7]">
            {/* Version column */}
            <td className="px-3 py-2.5 text-sm text-[#1d2129] whitespace-nowrap">
                <div className="flex items-center gap-2">
                    <span className="font-medium">V{version.version_no}</span>
                    {version.is_primary && (
                        <span className="inline-flex items-center rounded-sm bg-[#e8ffea] px-1.5 py-0.5 text-[11px] font-medium text-[#00b42a]">
                            {localize("com_knowledge.version.history_primary_badge")}
                        </span>
                    )}
                </div>
            </td>

            {/* File name column */}
            <td className="max-w-[180px] px-3 py-2.5">
                <span className="block truncate text-sm text-[#4e5969]" title={version.original_file_name}>
                    {version.original_file_name}
                </span>
            </td>

            {/* Uploader column */}
            <td className="px-3 py-2.5 text-sm text-[#86909c] whitespace-nowrap">
                {version.uploader_name ?? "—"}
            </td>

            {/* Upload time column */}
            <td className="px-3 py-2.5 text-sm text-[#86909c] whitespace-nowrap">
                {version.upload_time ? version.upload_time.replace("T", " ").slice(0, 16) : "—"}
            </td>

            {/* Parse status column */}
            <td className="px-3 py-2.5">
                <VersionStatusBadge parseStatus={version.status ?? 0} />
            </td>

            {/* File encoding column */}
            <td className="px-3 py-2.5 text-sm text-[#86909c]">
                {version.file_code ?? "—"}
            </td>

            {/* Actions column */}
            <td className="px-3 py-2.5">
                <div className="flex items-center gap-1.5">
                    {onPreview && (
                        <ActionButton
                            label={localize("com_knowledge.version.history_action_preview")}
                            onClick={() => onPreview(version.knowledge_file_id)}
                            disabled={anyPending}
                        >
                            <Eye className="size-4" />
                        </ActionButton>
                    )}
                    {onDownload && (
                        <ActionButton
                            label={localize("com_knowledge.version.history_action_download")}
                            onClick={() => onDownload(version.knowledge_file_id)}
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
}: VersionHistorySheetProps): JSX.Element | null {
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

    // Sort descending by version_no (newest first)
    const sortedVersions = [...versions].sort((a, b) => b.version_no - a.version_no);

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
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                side="right"
                className="flex h-full min-h-0 flex-col overflow-hidden p-0 w-[720px] sm:max-w-[720px]"
                hideClose
            >
                {/* Header */}
                <SheetHeader className="shrink-0 border-b border-[#e5e6eb] px-6 py-4 text-left">
                    <div className="flex items-center justify-between gap-4">
                        <div className="min-w-0">
                            <SheetTitle className="text-base font-semibold text-[#1d2129]">
                                {localize("com_knowledge.version.history_title")}
                            </SheetTitle>
                            {documentTitle && (
                                <p
                                    className="mt-0.5 truncate text-sm text-[#86909c]"
                                    title={documentTitle}
                                >
                                    {documentTitle}
                                </p>
                            )}
                        </div>
                        <Button
                            variant="ghost"
                            size="icon"
                            className="size-8 shrink-0 text-[#86909c] hover:bg-[#f2f3f5]"
                            onClick={() => onOpenChange(false)}
                        >
                            ✕
                        </Button>
                    </div>
                </SheetHeader>

                {/* Body */}
                <div className="flex-1 min-h-0 overflow-y-auto scrollbar-on-scroll px-6 py-4">
                    {isLoading ? (
                        <div className="flex h-32 items-center justify-center">
                            <Loader2 className="size-6 animate-spin text-[#86909c]" />
                        </div>
                    ) : sortedVersions.length === 0 ? (
                        <div className="flex h-32 items-center justify-center text-sm text-[#86909c]">
                            —
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full min-w-[640px] border-collapse text-sm">
                                <thead>
                                    <tr className="border-b border-[#e5e6eb] bg-[#fafafa]">
                                        <th className="px-3 py-2 text-left text-xs font-medium text-[#4e5969]">
                                            {localize("com_knowledge.version.history_col_version")}
                                        </th>
                                        <th className="px-3 py-2 text-left text-xs font-medium text-[#4e5969]">
                                            {localize("com_knowledge.version.history_col_filename")}
                                        </th>
                                        <th className="px-3 py-2 text-left text-xs font-medium text-[#4e5969]">
                                            {localize("com_knowledge.version.history_col_uploader")}
                                        </th>
                                        <th className="px-3 py-2 text-left text-xs font-medium text-[#4e5969]">
                                            {localize("com_knowledge.version.history_col_upload_time")}
                                        </th>
                                        <th className="px-3 py-2 text-left text-xs font-medium text-[#4e5969]">
                                            {localize("com_knowledge.version.history_col_parse_status")}
                                        </th>
                                        <th className="px-3 py-2 text-left text-xs font-medium text-[#4e5969]">
                                            {localize("com_knowledge.version.history_col_file_encoding")}
                                        </th>
                                        <th className="px-3 py-2 text-left text-xs font-medium text-[#4e5969]">
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
            </SheetContent>
        </Sheet>
    );
}
