import { Button, Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { FileSearch, GitBranch, History } from "lucide-react";
import { useState } from "react";

import { FileStatus, FileType, type KnowledgeFile } from "~/api/knowledge";
import { Checkbox, DropdownMenu, DropdownMenuTrigger } from "~/components";
import { ActionMenuContent, ActionMenuItem } from "~/components/ActionMenu";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { canDecidePendingUpload, canWithdrawPendingUpload, getFileChangeLockState, isPendingUploadSelectable } from "../hooks/useFileChangeApproval";
import { useInlineRename } from "../hooks/useInlineRename";
import {
    formatTimeCard,
    getKnowledgeApprovalStatusLabel,
    type KnowledgeStatusTone,
    isKnowledgeApprovalRejected,
    isKnowledgeItemPreviewable,
    isKnowledgeItemUploading,
} from "../knowledgeUtils";
import { FileChangeActionIcon } from "./FileChangeActionIcon";
import { FileChangePendingTooltip } from "./FileChangePendingTooltip";
import FileIconRenderer from "./FileIcon";
import { PendingUploadApprovalActions } from "./PendingUploadApprovalActions";
import { SELECTION_CHECKBOX_CLASS } from "./selectionCheckboxStyles";
import TagGroup from "./TagGroup";

/**
 * Desktop list-view row (Figma 13198:75866).
 *
 * Replaces the old column table: 56px tall, zebra-striped, no headers. Each row
 * is 16px gutter → checkbox → 32px thumbnail → title over a `time | tags`
 * meta line → status pill → row actions. The layout mirrors the H5 list row
 * (FileCard `mobileListMode`); the desktop differences — left-hand checkbox,
 * 32px thumbnail, always-visible download/more buttons — are why it is its own
 * component rather than another branch inside FileCard.
 */

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Highlight case-insensitive matches of `keyword` inside `text` (Figma 11814:70449). */
const renderHighlightedName = (text: string, keyword?: string) => {
    const kw = keyword?.trim();
    if (!kw) return text;
    const parts = text.split(new RegExp(`(${escapeRegExp(kw)})`, "gi"));
    const lowerKw = kw.toLowerCase();
    return parts.map((part, i) =>
        part.toLowerCase() === lowerKw
            ? <span key={i} className="text-blue-500">{part}</span>
            : part
    );
};

/**
 * Status pill shown on the right of the row, before the action buttons
 * (Figma 13199:86506). Successful files intentionally have no pill.
 */
const StatusBadge = ({ file, onOpenApprovalDetail }: {
    file: KnowledgeFile;
    onOpenApprovalDetail?: (requestId: number) => void;
}) => {
    const localize = useLocalize();
    const status = file.status ?? FileStatus.SUCCESS;
    const fileChangeLock = getFileChangeLockState(file);
    const approvalStatusLabel = getKnowledgeApprovalStatusLabel(file);
    const statusReason = file.approvalReason?.trim() || file.errorMessage?.trim() || null;
    const pendingUpload = file.pendingUploadApproval;

    if (pendingUpload) {
        const failed = pendingUpload.status === "failed";
        // While the approval instance is still open the row reads as pending in
        // neutral grey — the business execution status ("queued" …) only becomes
        // meaningful once a decision has been made. An approver reads "待审核"
        // (it is on their desk), everyone else "审核中".
        const awaitingDecision = pendingUpload.approvalStatus === "pending";
        const pendingLabel = localize(
            pendingUpload.canApprove
                ? "com_knowledge.file_change_pending_approver"
                : "com_knowledge.file_change_pending_applicant",
        );
        const pill = (
            <button
                type="button"
                className={cn(
                    "inline-flex shrink-0 items-center gap-1 rounded px-2 text-caption leading-5",
                    awaitingDecision
                        ? "bg-fill-2 text-text-3"
                        : failed ? "bg-danger/10 text-danger" : "bg-success/10 text-success",
                )}
                onClick={(event) => {
                    event.stopPropagation();
                    onOpenApprovalDetail?.(pendingUpload.requestId);
                }}
            >
                {awaitingDecision ? (
                    <FileChangeActionIcon action="upload" />
                ) : (
                    <span className={cn("size-1 rounded-full", failed ? "bg-danger" : "bg-success")} />
                )}
                {awaitingDecision
                    ? pendingLabel
                    : localize(`com_knowledge.file_change_status_${pendingUpload.status}`)}
            </button>
        );
        return awaitingDecision
            ? <FileChangePendingTooltip file={file} side="left">{pill}</FileChangePendingTooltip>
            : pill;
    }

    if (fileChangeLock.showBadge && file.fileChangeApproval) {
        // rename / move / delete awaiting approval — same neutral pill as a
        // pending upload, so all four change actions read alike.
        return (
            <FileChangePendingTooltip file={file} side="left">
                <button
                    type="button"
                    className="inline-flex shrink-0 items-center gap-1 rounded bg-fill-2 px-2 text-caption leading-5 text-text-3"
                    onClick={(event) => {
                        event.stopPropagation();
                        onOpenApprovalDetail?.(file.fileChangeApproval!.requestId);
                    }}
                >
                    <FileChangeActionIcon action={file.fileChangeApproval.action} />
                    {localize(
                        file.fileChangeApproval.canApprove
                            ? "com_knowledge.file_change_pending_approver"
                            : "com_knowledge.file_change_pending_applicant",
                    )}
                </button>
            </FileChangePendingTooltip>
        );
    }

    // Folder rollup: a folder whose subtree holds a failed / timed-out / flagged file reads
    // 存在异常, and that wins over any in-progress state below it. The backend walks the whole
    // subtree by path prefix, so every ancestor level lights up, not just the direct parent.
    const isFolderWithAbnormal = file.type === FileType.FOLDER && file.hasAbnormalFiles === true;

    if (status === FileStatus.SUCCESS && !approvalStatusLabel && !isFolderWithAbnormal) return null;

    let label: string;
    let tone: KnowledgeStatusTone;
    if (isFolderWithAbnormal) {
        label = localize("com_knowledge.folder_abnormal");
        tone = "danger";
    } else if (approvalStatusLabel) {
        label = approvalStatusLabel;
        // `finalize_failed` lands in `approving` blue with the rest of the
        // non-rejected approval labels — that is what this row painted before
        // the migration. It reads like a failure and probably wants `danger`;
        // left alone here so the migration changes no state's meaning.
        tone = isKnowledgeApprovalRejected(file) ? "danger" : "approving";
    } else {
        const config: Record<string, { label: string; tone: KnowledgeStatusTone }> = {
            [FileStatus.PROCESSING]: { label: localize("com_knowledge.parsing_status"), tone: "default" },
            [FileStatus.WAITING]: { label: localize("com_knowledge.queueing_status"), tone: "default" },
            [FileStatus.REBUILDING]: { label: localize("com_knowledge.rebuilding_status"), tone: "default" },
            [FileStatus.UPLOADING]: { label: localize("com_knowledge.uploading_status"), tone: "default" },
            [FileStatus.FAILED]: { label: localize("com_knowledge.fail"), tone: "danger" },
            [FileStatus.TIMEOUT]: { label: localize("com_knowledge.timeout"), tone: "danger" },
            [FileStatus.VIOLATION]: { label: localize("com_knowledge.violation"), tone: "danger" },
        };
        const item = config[status] || config[FileStatus.WAITING];
        label = item.label;
        tone = item.tone;
    }

    // 组件-Tag标签.md §5 — the status form: a dot the color of the text, in
    // front of one word. `small` is the list-row rung. The row lays its
    // children out in a flex line, so the tag keeps its own width.
    const pill = (
        <Tag size="small" dot color={tone} className="shrink-0 whitespace-nowrap">
            {label}
        </Tag>
    );

    // Queueing carries no actionable reason — skip the tooltip there. The folder rollup
    // deliberately shows no reason either: the user opens the folder to see which file failed.
    if (!statusReason || status === FileStatus.WAITING || isFolderWithAbnormal) return pill;
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <div className="inline-flex max-w-full">{pill}</div>
            </TooltipTrigger>
            <TooltipContent noArrow side="top" className="max-w-[320px] rounded-md bg-[#1D2129] px-3 py-2 text-left text-xs leading-5 text-white">
                {statusReason}
            </TooltipContent>
        </Tooltip>
    );
};

export interface FileListRowProps {
    file: KnowledgeFile;
    /** Row position, for the zebra stripe (Figma 13198:75866). */
    index: number;
    isAdmin: boolean;
    /** F040: lazily resolve this file's action permissions when its menu opens. */
    onEnsureFilePermissions?: (file: KnowledgeFile) => void;
    isSelected: boolean;
    onSelect: (selected: boolean) => void;
    onDownload: () => void;
    onEditTags: () => void;
    onRename: (newName: string) => void;
    onDelete: () => void;
    onRetry: () => void;
    onNavigateFolder?: () => void;
    onPreview?: () => void;
    onValidateName?: (newName: string) => string | null;
    onCancelCreate?: () => void;
    onManagePermission?: () => void;
    /** F034: open the move dialog for this file/folder. Shown when provided. */
    onMove?: () => void;
    canMove?: boolean;
    canRename?: boolean;
    canDelete?: boolean;
    canDownload?: boolean;
    /** Version management gating for per-row version actions / badges. */
    versionManagementEnabled?: boolean;
    onOpenVersionManagement?: (file: KnowledgeFile) => void;
    onOpenVersionHistory?: (file: KnowledgeFile) => void;
    /** Whether the current user can manage members (gates the "similar" pill). */
    canManageMembers?: boolean;
    /** Shougang: file encoding is appended to the meta line instead of its own column. */
    shougangEnabled?: boolean;
    canEditEncoding?: boolean;
    onEditEncoding?: (file: KnowledgeFile) => void;
    /** Tag IDs hit by the active search; matching tags are highlighted in TagGroup. */
    highlightedTagIds?: number[];
    /** Keyword hit by the active search; matching substring in the file name is highlighted. */
    highlightKeyword?: string;
    // F034 drag-move: row is a drag source; folder rows are drop targets.
    rowDraggable?: boolean;
    onRowDragStart?: (e: React.DragEvent) => void;
    isFolderDragOver?: boolean;
    onFolderDragOver?: (e: React.DragEvent) => void;
    onFolderDragLeave?: () => void;
    onFolderDrop?: (e: React.DragEvent) => void;
    onOpenApprovalDetail?: (requestId: number) => void;
    onPreviewPendingUpload?: (requestId: number) => void;
    onDecidePendingUpload?: (requestId: number, action: "approve" | "reject") => void;
    /** Row-level withdraw for the applicant's own pending upload. */
    onWithdrawPendingUpload?: (requestId: number) => void;
    pendingUploadDeciding?: boolean;
    /** Current viewer id, to tell whether a pending row is the viewer's to withdraw. */
    currentUserId?: string | number;
}

export function FileListRow({
    file,
    index,
    isAdmin,
    onEnsureFilePermissions,
    isSelected,
    onSelect,
    onDownload,
    onEditTags,
    onRename,
    onDelete,
    onRetry,
    onNavigateFolder,
    onPreview,
    onValidateName,
    onCancelCreate,
    onManagePermission,
    onMove,
    canMove = false,
    canRename = false,
    canDelete = false,
    canDownload = false,
    versionManagementEnabled = false,
    onOpenVersionManagement,
    onOpenVersionHistory,
    canManageMembers = false,
    shougangEnabled = false,
    canEditEncoding = false,
    onEditEncoding,
    highlightedTagIds,
    highlightKeyword,
    rowDraggable = false,
    onRowDragStart,
    isFolderDragOver = false,
    onFolderDragOver,
    onFolderDragLeave,
    onFolderDrop,
    onOpenApprovalDetail,
    onPreviewPendingUpload,
    onDecidePendingUpload,
    onWithdrawPendingUpload,
    pendingUploadDeciding = false,
    currentUserId,
}: FileListRowProps) {
    const localize = useLocalize();
    const [moreMenuOpen, setMoreMenuOpen] = useState(false);
    const [contextMenuOpen, setContextMenuOpen] = useState(false);
    const [contextMenuPosition, setContextMenuPosition] = useState({ x: 0, y: 0 });

    const isFolder = file.type === FileType.FOLDER;
    const isCreating = !!file.isCreating;
    const pendingUpload = file.pendingUploadApproval;
    const canDecidePending = canDecidePendingUpload(pendingUpload);
    const canWithdrawPending = canWithdrawPendingUpload(pendingUpload, currentUserId);
    const isUploading = isKnowledgeItemUploading(file);
    const fileChangeLock = getFileChangeLockState(file);
    // A folder still uploading its batch: faded, not clickable, checkbox greyed out.
    const isUploadingFolderPlaceholder = isFolder && isUploading && !isCreating;
    const namePreviewable = Boolean(pendingUpload) || isKnowledgeItemPreviewable(file);
    // A pending-upload row is selectable only while awaiting a decision (审核中):
    // the applicant can batch-withdraw and an approver can batch-decide. Once
    // decided it moves into an execution state (处理中/执行失败/…) with no batch
    // semantics, so it keeps a disabled checkbox. The frontend-only folder upload
    // placeholder (no backend identity) also stays unselectable.
    const isSelectable = pendingUpload
        ? isPendingUploadSelectable(pendingUpload)
        : !isUploadingFolderPlaceholder;
    // Shared look for every button in the row-action strip. rounded-lg (8px)
    // overrides the size variant's rounded-md (6px). The hover fill flips on a
    // selected row: the default neutral step reads as a faint smudge over the
    // brand tint, so the button lifts towards white instead — same contrast cue,
    // opposite direction, semi-transparent so it thins the tint rather than
    // punching an opaque white hole in the row.
    const rowActionClass = cn(
        "rounded-lg",
        isSelected ? "hover:bg-white/60" : "hover:bg-btn-fill-2",
    );

    // F040: resolve this file's action permissions lazily, only when the menu opens.
    const handleMoreMenuOpenChange = (open: boolean) => {
        setMoreMenuOpen(open);
        if (open) onEnsureFilePermissions?.(file);
    };

    const {
        isRenaming,
        renameValue,
        setRenameValue,
        inputRef,
        handleRenameSubmit,
        handleKeyDown,
        startRenaming,
    } = useInlineRename({
        fileName: file.name,
        isFolder,
        isCreating,
        onRename,
        onValidateName,
        onCancelCreate,
    });

    const hasRetryOption = Boolean(
        file.status === FileStatus.FAILED ||
        file.status === FileStatus.VIOLATION ||
        (isFolder && file.hasFailedFiles === true)
    );
    const showMoveItem = Boolean(onMove) && !isCreating;
    const showVersionManagement = versionManagementEnabled && !isFolder && file.status === FileStatus.SUCCESS && isAdmin && Boolean(onOpenVersionManagement);
    const showVersionHistory = versionManagementEnabled && !isFolder && Boolean(file.is_multi_version) && Boolean(onOpenVersionHistory);
    // Placeholders have only a temp id (no backend identity) — suppress all row actions.
    const showMoreMenu = !pendingUpload && !isUploadingFolderPlaceholder && (
        canDownload || isAdmin || canRename || canDelete || Boolean(onManagePermission)
        || showMoveItem || showVersionManagement || showVersionHistory
    );

    const moreMenuItems = (
        <>
            {isAdmin && !isFolder && (
                <ActionMenuItem
                    onClick={(e) => { e.stopPropagation(); onEditTags(); }}
                    icon={<Outlined.Tag />}
                    label={localize("com_knowledge.edit_tags")}
                />
            )}
            {canRename && (
                <ActionMenuItem
                    disabled={fileChangeLock.locked}
                    onClick={(e) => { e.stopPropagation(); if (!fileChangeLock.locked) startRenaming(); }}
                    icon={<Outlined.Edit />}
                    label={localize("com_knowledge.rename")}
                />
            )}
            {showMoveItem && (
                <ActionMenuItem
                    disabled={!canMove || isUploading || fileChangeLock.locked}
                    onClick={(e) => { e.stopPropagation(); onMove?.(); }}
                    icon={<Outlined.MoveToFolder />}
                    label={localize("com_knowledge.move")}
                />
            )}
            {isAdmin && hasRetryOption && (
                <ActionMenuItem
                    onClick={(e) => { e.stopPropagation(); onRetry?.(); }}
                    icon={<Outlined.Refresh />}
                    label={localize("com_knowledge.retry")}
                />
            )}
            {onManagePermission && (
                <ActionMenuItem
                    onClick={(e) => { e.stopPropagation(); onManagePermission(); }}
                    icon={<Outlined.PeopleSafe />}
                    label={localize("com_permission.manage_permission")}
                />
            )}
            {showVersionManagement && (
                <ActionMenuItem
                    onClick={(e) => { e.stopPropagation(); onOpenVersionManagement?.(file); }}
                    icon={<GitBranch />}
                    label={localize("com_knowledge.version.menu_version_management")}
                />
            )}
            {showVersionHistory && (
                <ActionMenuItem
                    onClick={(e) => { e.stopPropagation(); onOpenVersionHistory?.(file); }}
                    icon={<History />}
                    label={localize("com_knowledge.version.menu_version_history")}
                />
            )}
            {canDelete && (
                <ActionMenuItem
                    danger
                    disabled={fileChangeLock.locked}
                    onClick={(e) => { e.stopPropagation(); if (!fileChangeLock.locked) onDelete(); }}
                    icon={<Outlined.Delete />}
                    label={localize("com_knowledge.delete")}
                />
            )}
        </>
    );

    const handleRowContextMenu = (e: React.MouseEvent<HTMLDivElement>) => {
        if (!showMoreMenu) return;
        e.preventDefault();
        // Same lazy permission resolution as the "..." trigger, otherwise the
        // right-click menu renders with unresolved (reduced) permissions.
        onEnsureFilePermissions?.(file);
        setContextMenuPosition({ x: e.clientX, y: e.clientY });
        setContextMenuOpen(true);
    };

    const handleOpen = () => {
        if (isCreating || isRenaming || isUploadingFolderPlaceholder) return;
        if (pendingUpload) {
            onPreviewPendingUpload?.(pendingUpload.requestId);
            return;
        }
        if (isFolder) {
            onNavigateFolder?.();
            return;
        }
        if (!namePreviewable) return;
        onPreview?.();
    };

    // The whole row is a selection target; only the name (and rename input /
    // action buttons, which stop propagation) opts out and opens the detail.
    const handleRowClick = () => {
        if (!isSelectable || isCreating || isRenaming) return;
        onSelect(!isSelected);
    };

    const showEncoding = shougangEnabled && !isFolder;

    return (
        <div
            data-knowledge-file-item
            draggable={!pendingUpload && rowDraggable && !isCreating && !isRenaming && !isUploading}
            onDragStart={rowDraggable ? onRowDragStart : undefined}
            onDragOver={isFolder && !isUploadingFolderPlaceholder ? onFolderDragOver : undefined}
            onDragLeave={isFolder && !isUploadingFolderPlaceholder ? onFolderDragLeave : undefined}
            onDrop={isFolder && !isUploadingFolderPlaceholder ? onFolderDrop : undefined}
            onContextMenu={handleRowContextMenu}
            onClick={handleRowClick}
            className={cn(
                // Zebra base (Figma 13198:75866) — selection / drag-over / hover paint over it.
                "group relative flex h-14 items-center gap-2 px-4 transition-colors",
                isSelectable && !isCreating && "cursor-pointer",
                index % 2 === 1 ? "bg-[#fbfbfb]" : "bg-white",
                isFolderDragOver && "bg-blue-100",
                !isSelected && !isFolderDragOver && "hover:bg-fill-1",
            )}
            style={isSelected ? { backgroundColor: "rgb(var(--brand-500)/0.07)" } : undefined}
        >
            {/* Always rendered — an unselectable row shows a disabled checkbox rather
                than an empty slot, so the column never breaks alignment. Mirrors
                `isSelectableFile` in the page container. */}
            <Checkbox
                checked={isSelected}
                onCheckedChange={onSelect}
                // The row's own click also toggles selection — without this the
                // two handlers would cancel each other out on a checkbox click.
                onClick={(e) => e.stopPropagation()}
                disabled={!isSelectable}
                className={cn(
                    "size-4 shrink-0",
                    SELECTION_CHECKBOX_CLASS,
                    !isSelectable && "cursor-not-allowed opacity-50",
                )}
            />

            <div
                className={cn(
                    "relative flex size-8 shrink-0 items-center justify-center overflow-hidden rounded",
                    isUploadingFolderPlaceholder && "opacity-50",
                )}
            >
                <FileIconRenderer file={file} isFolder={isFolder} iconClassName="size-8 shrink-0" thumbBordered transparentBg />
            </div>

            <div className="flex min-w-0 flex-1 flex-col justify-center">
                {isRenaming ? (
                    <input
                        ref={inputRef}
                        type="text"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onBlur={handleRenameSubmit}
                        onKeyDown={handleKeyDown}
                        onClick={(e) => e.stopPropagation()}
                        className="h-7 w-full rounded border border-border-deep bg-white px-2 text-sm font-normal shadow-focus outline-none"
                    />
                ) : (
                    <>
                        <div className="flex min-w-0 items-center gap-1.5">
                            {versionManagementEnabled && file.is_multi_version && file.version_no != null && file.version_no >= 1 && (
                                <span className="flex h-5 shrink-0 items-center justify-center rounded bg-blue-50 px-1.5 text-xs font-medium text-blue-500">
                                    {`V${file.version_no}`}
                                </span>
                            )}
                            <span
                                className={cn(
                                    "min-w-0 truncate text-sm leading-[22px]",
                                    namePreviewable && !isUploadingFolderPlaceholder
                                        ? "cursor-pointer text-text-1 hover:text-blue-500"
                                        : "cursor-default text-text-3",
                                    isUploadingFolderPlaceholder && "opacity-50",
                                )}
                                // A name that can't open anything falls through to the
                                // row's select-toggle instead of dead-ending the click.
                                onClick={(e) => {
                                    if (!namePreviewable || isUploadingFolderPlaceholder) return;
                                    e.stopPropagation();
                                    handleOpen();
                                }}
                            >
                                {renderHighlightedName(file.name, highlightKeyword)}
                            </span>
                            {versionManagementEnabled && canManageMembers && file.has_similar && !file.is_multi_version && file.status === FileStatus.SUCCESS && (
                                <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); onOpenVersionManagement?.(file); }}
                                    className="flex h-5 shrink-0 items-center gap-1 rounded bg-[#FFF3E8] px-1.5 text-xs text-[#F76F44] hover:bg-[#FFE6D2]"
                                >
                                    <FileSearch className="size-3" />
                                    {localize("com_knowledge.version.pill_similar")}
                                </button>
                            )}
                        </div>

                        {/* Meta line: time | tags | encoding (Figma 13198:75880). */}
                        <div className="mt-0.5 flex min-w-0 items-center gap-1.5 overflow-hidden">
                            <span className="shrink-0 text-[10px] leading-[18px] text-text-3 tabular-nums">
                                {formatTimeCard(file.updatedAt)}
                            </span>
                            {!isFolder && file.tags && file.tags.length > 0 && (
                                <>
                                    <span className="h-2.5 w-px shrink-0 bg-border-base" aria-hidden />
                                    <TagGroup
                                        tags={file.tags}
                                        variant="text-list"
                                        highlightedTagIds={highlightedTagIds}
                                        actionButton={
                                            isAdmin ? (
                                                <button
                                                    type="button"
                                                    title={localize("com_knowledge.edit_tags")}
                                                    onClick={(e) => { e.stopPropagation(); onEditTags(); }}
                                                    className="hidden cursor-pointer items-center justify-center text-text-2 transition-colors hover:text-blue-500 group-hover:flex"
                                                >
                                                    <Outlined.Edit className="size-3" />
                                                </button>
                                            ) : undefined
                                        }
                                    />
                                </>
                            )}
                            {showEncoding && (file.fileEncoding || file.status === FileStatus.PROCESSING) && (
                                <>
                                    <span className="h-2.5 w-px shrink-0 bg-border-base" aria-hidden />
                                    {file.fileEncoding ? (
                                        <span className="truncate text-[10px] leading-[18px] text-text-3" title={file.fileEncoding}>
                                            {file.fileEncoding}
                                        </span>
                                    ) : (
                                        <span className="shrink-0 text-[10px] italic leading-[18px] text-text-3">
                                            {localize("com_knowledge.file_encoding_generating")}
                                        </span>
                                    )}
                                    {file.fileEncoding && canEditEncoding && (
                                        <button
                                            type="button"
                                            title={localize("com_knowledge.file_encoding_edit_title")}
                                            onClick={(e) => { e.stopPropagation(); onEditEncoding?.(file); }}
                                            className="hidden shrink-0 cursor-pointer items-center justify-center text-text-2 transition-colors hover:text-blue-500 group-hover:flex"
                                        >
                                            <Outlined.Edit className="size-3" />
                                        </button>
                                    )}
                                </>
                            )}
                        </div>
                    </>
                )}
            </div>

            <StatusBadge file={file} onOpenApprovalDetail={onOpenApprovalDetail} />

            {/* The action slot keeps its width even when a row has one button or
                none, so status pills line up down the column. 73px = two 32px
                action buttons + the 9px divider between them. */}
            {/* stopPropagation: opening a row menu must not toggle the row's selection. */}
            <div
                className="flex min-w-[73px] shrink-0 items-center justify-end"
                onClick={(e) => e.stopPropagation()}
            >
                {pendingUpload && (canDecidePending || canWithdrawPending) && (
                    <PendingUploadApprovalActions
                        requestId={pendingUpload.requestId}
                        disabled={pendingUploadDeciding}
                        onDecide={canDecidePending ? onDecidePendingUpload : undefined}
                        onWithdraw={canWithdrawPending ? onWithdrawPendingUpload : undefined}
                        hoverClassName={rowActionClass}
                    />
                )}
                {canDownload && (
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                color="default"
                                variant="text"
                                size="medium"
                                iconOnly
                                className={rowActionClass}
                                aria-label={localize("com_knowledge.download")}
                                onClick={(e) => { e.stopPropagation(); onDownload(); }}
                            >
                                <Outlined.Download />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent>{localize("com_knowledge.download")}</TooltipContent>
                    </Tooltip>
                )}
                {canDownload && showMoreMenu && (
                    <span aria-hidden className="mx-1 h-2 w-px shrink-0 bg-border-base" />
                )}
                {showMoreMenu && (
                    <DropdownMenu open={moreMenuOpen} onOpenChange={handleMoreMenuOpenChange}>
                        <DropdownMenuTrigger asChild>
                            {/* No Tooltip here: a tooltip on a menu trigger lingers over the
                                open menu unless it is manually suppressed (see KnowledgeBreadcrumb).
                                The menu itself names the actions, so aria-label alone is enough. */}
                            <Button
                                color="default"
                                variant="text"
                                size="medium"
                                iconOnly
                                className={rowActionClass}
                                aria-label={localize("com_knowledge_operation")}
                            >
                                <Outlined.More />
                            </Button>
                        </DropdownMenuTrigger>
                        <ActionMenuContent align="end" width={140}>{moreMenuItems}</ActionMenuContent>
                    </DropdownMenu>
                )}
            </div>

            {/* Right-click menu: an invisible cursor-anchored trigger drives the same items as the "..." menu. */}
            {showMoreMenu && (
                <DropdownMenu open={contextMenuOpen} onOpenChange={setContextMenuOpen}>
                    <DropdownMenuTrigger asChild>
                        <button
                            type="button"
                            aria-hidden="true"
                            tabIndex={-1}
                            className="fixed size-0 opacity-0"
                            style={{ left: contextMenuPosition.x, top: contextMenuPosition.y }}
                        />
                    </DropdownMenuTrigger>
                    <ActionMenuContent align="start" width={140}>{moreMenuItems}</ActionMenuContent>
                </DropdownMenu>
            )}
        </div>
    );
}
