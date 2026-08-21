import { Download, MoreVertical, GitBranch, History, FileSearch } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { useState, type MouseEvent } from "react";
import { FileStatus, FileType, KnowledgeFile, SpaceRole } from "~/api/knowledge";
import { Button, Checkbox } from "~/components";
import { RoundCheckbox } from "~/components/ui/RoundCheckbox";
import { SELECTION_CHECKBOX_CLASS } from "./selectionCheckboxStyles";
import { Card, CardContent } from "~/components/ui/Card";
import {
    DropdownMenu,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import { ActionMenuContent, ActionMenuItem } from "~/components/ActionMenu";
import { cn } from "~/utils";
import { FileChangeActionIcon } from "./FileChangeActionIcon";
import { FileChangePendingTooltip } from "./FileChangePendingTooltip";
import FileIconRenderer from "./FileIcon";
import TagGroup from "./TagGroup";
import { useInlineRename } from "../hooks/useInlineRename";
import { formatTimeCard, getKnowledgeApprovalStatusLabel, isKnowledgeApprovalRejected, isKnowledgeItemPreviewable, isKnowledgeItemUploading } from "../knowledgeUtils";
import { useLocalize, useMediaQuery } from "~/hooks";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { canDecidePendingUpload, canWithdrawPendingUpload, getFileChangeLockState, isPendingUploadSelectable } from "../hooks/useFileChangeApproval";
import { PendingUploadApprovalActions } from "./PendingUploadApprovalActions";

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

interface FileCardProps {
    file: KnowledgeFile;
    userRole: SpaceRole;
    /** F040: lazily resolve this file's action permissions when its menu opens. */
    onEnsureFilePermissions?: (file: KnowledgeFile) => void;
    isSelected: boolean;
    onSelect: (selected: boolean) => void;
    onDownload: () => void;
    onRename: (newName: string) => void;
    onDelete: () => void;
    onEditTags: () => void;
    onRetry?: () => void;
    onNavigateFolder?: (folderId?: string) => void;
    onPreview?: (fileId: string) => void;
    onValidateName?: (newName: string) => string | null;
    onCancelCreate?: () => void;
    onManagePermission?: () => void;
    /** F034: open the move dialog for this file/folder. Shown when provided. */
    onMove?: () => void;
    /** F034: whether this file/folder can be moved (move permission in this space). */
    canMove?: boolean;
    canRename?: boolean;
    canDelete?: boolean;
    canDownload?: boolean;
    /** Version management gating for per-row version actions / badges. */
    versionManagementEnabled?: boolean;
    /** Open the version-management (similar-document linking) dialog for this file. */
    onOpenVersionManagement?: (file: KnowledgeFile) => void;
    /** Open the version-history sheet for this file. */
    onOpenVersionHistory?: (file: KnowledgeFile) => void;
    /** Whether the current user can manage members (gates the "similar" pill). */
    canManageMembers?: boolean;
    disableClickNavigate?: boolean;
    hideSelectionCheckbox?: boolean;
    /** H5: render as list-row (not card tile). */
    mobileListMode?: boolean;
    /** Hide per-file download UI (icon + menu item), e.g. in read-only preview drawers. */
    hideDownloadActions?: boolean;
    /** Tag IDs hit by the active search; matching tags are highlighted in TagGroup. */
    highlightedTagIds?: number[];
    /** Keyword hit by the active search; matching substring in the file name is highlighted. */
    highlightKeyword?: string;
    // F034 drag-move: card is a drag source; folder cards are drop targets.
    cardDraggable?: boolean;
    onCardDragStart?: (e: React.DragEvent) => void;
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

export function FileCard({
    file,
    userRole,
    onEnsureFilePermissions,
    isSelected,
    onSelect,
    onDownload,
    onRename,
    onDelete,
    onEditTags,
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
    disableClickNavigate = false,
    hideSelectionCheckbox = false,
    mobileListMode = false,
    hideDownloadActions = false,
    highlightedTagIds,
    highlightKeyword,
    cardDraggable = false,
    onCardDragStart,
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
}: FileCardProps) {
    const localize = useLocalize();
    /** True when primary input is mouse + hover: actions reveal on card hover. Touch / coarse pointer: keep actions visible (viewport width does not matter). */
    const revealCardActionsOnHoverOnly = useMediaQuery(
        "(hover: hover) and (pointer: fine)",
    );
    const isCreating = !!file.isCreating;
    const pendingUpload = file.pendingUploadApproval;
    const canDecidePending = canDecidePendingUpload(pendingUpload);
    const canWithdrawPending = canWithdrawPendingUpload(pendingUpload, currentUserId);
    // Uploading placeholder cards have no backend identity yet — not movable.
    const isUploading = isKnowledgeItemUploading(file);
    const fileChangeLock = getFileChangeLockState(file);
    const [hovered, setHovered] = useState(false);
    const [moreMenuOpen, setMoreMenuOpen] = useState(false);
    // F040: resolve this file's action permissions lazily, only when the menu opens.
    const handleMoreMenuOpenChange = (open: boolean) => {
        setMoreMenuOpen(open);
        if (open) onEnsureFilePermissions?.(file);
    };
    // Right-click context menu mirrors the "..." action menu, positioned at the cursor.
    const [contextMenuOpen, setContextMenuOpen] = useState(false);
    const [contextMenuPosition, setContextMenuPosition] = useState({ x: 0, y: 0 });
    const failureMessage = (
        file.status === FileStatus.FAILED ||
        file.status === FileStatus.TIMEOUT ||
        file.status === FileStatus.VIOLATION
    ) && file.errorMessage?.trim()
        ? file.errorMessage.trim()
        : null;
    const approvalStatusLabel = getKnowledgeApprovalStatusLabel(file);
    const approvalReason = file.approvalReason?.trim() || null;

    const isAdmin = userRole === SpaceRole.CREATOR || userRole === SpaceRole.ADMIN;
    const isFolder = file.type === FileType.FOLDER;
    // A folder still uploading its batch: shown only as a name with a translucent
    // "uploading" overlay, not clickable, not a drag source / drop target.
    // Inline-create placeholders (isCreating) are excluded — a freshly created
    // folder is a normal folder with a highlighted rename input, no scrim/tag.
    const isUploadingFolderPlaceholder = isFolder && isUploading && !isCreating;
    // A pending-upload row is selectable only while awaiting a decision (审核中):
    // the applicant can batch-withdraw and an approver can batch-decide. Once
    // decided it moves into an execution state (处理中/执行失败/…) with no batch
    // semantics, so it keeps a disabled checkbox. The frontend-only folder upload
    // placeholder (no backend identity) also stays unselectable. Unselectable rows
    // keep a disabled checkbox instead of dropping it, so the column stays put.
    const isSelectable = pendingUpload
        ? isPendingUploadSelectable(pendingUpload)
        : !isUploadingFolderPlaceholder;
    /** Files that haven't finished parsing get the neutral grey skin (Figma 11671:34497). */
    const isNotParsed = !isFolder && !!file.status && file.status !== FileStatus.SUCCESS;
    /** Subset of isNotParsed that should show the "In progress" overlay tag. */
    const isInProgress = !isFolder && (
        file.status === FileStatus.UPLOADING ||
        file.status === FileStatus.PROCESSING ||
        file.status === FileStatus.WAITING ||
        file.status === FileStatus.REBUILDING
    );

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

    // formatTime is now imported from ../knowledgeUtils

    const nameToneClass = (pendingUpload || isKnowledgeItemPreviewable(file))
        ? "text-text-1"
        : "text-text-3";

    /**
     * Status pill overlaid on the bottom-left of the preview area (Figma 11671:34497).
     * Covers all non-success states: parsing-like (neutral grey) + error / approval (colored).
     */
    const renderStatusOverlayTag = (inline = false) => {
        if (pendingUpload) {
            const failed = pendingUpload.status === "failed";
            // Still awaiting a decision → neutral pill; the business execution
            // status only carries meaning once the request has been approved.
            // An approver reads "待审核" (it is on their desk), everyone else "审核中".
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
                        "inline-flex items-center justify-center gap-1 rounded px-2 text-caption",
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
            const tipped = awaitingDecision
                ? (
                    <FileChangePendingTooltip file={file} side={inline ? "left" : "top"}>
                        {pill}
                    </FileChangePendingTooltip>
                )
                : pill;
            return inline ? tipped : <div className="absolute bottom-1 left-1 z-20">{tipped}</div>;
        }
        if (fileChangeLock.showBadge && file.fileChangeApproval) {
            // rename / move / delete awaiting approval — same neutral pill as a
            // pending upload, so all four change actions read alike.
            const pill = (
                <button
                    type="button"
                    className="inline-flex items-center justify-center gap-1 rounded bg-fill-2 px-2 text-caption text-text-3"
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
            );
            const tipped = (
                <FileChangePendingTooltip file={file} side={inline ? "left" : "top"}>
                    {pill}
                </FileChangePendingTooltip>
            );
            return inline ? tipped : <div className="absolute bottom-1 left-1 z-20">{tipped}</div>;
        }
        // Uploading folder placeholder: a neutral "uploading" pill in the same
        // bottom-left slot as the file status tags — no spinner over the icon.
        if (isUploadingFolderPlaceholder) {
            const pill = (
                <div className="inline-flex items-center justify-center gap-1 rounded-[4px] bg-[#f2f4f7] px-2">
                    <span className="size-1 shrink-0 rounded-full bg-[#6b7785]" />
                    <span className="whitespace-nowrap text-xs leading-5 text-[#6b7785]">
                        {localize("com_knowledge.uploading_status")}
                    </span>
                </div>
            );
            // z-20 keeps the tag crisp above the translucent uploading scrim (z-10).
            return inline ? pill : <div className="absolute bottom-1 left-1 z-20">{pill}</div>;
        }
        if (!isAdmin || isFolder) return null;
        if (file.status === FileStatus.SUCCESS) return null;

        const approvalLabel = approvalStatusLabel;
        const statusReason = failureMessage || approvalReason;

        type Tone = { bg: string; text: string; dot: string };
        const neutralTone: Tone = { bg: "bg-[#f2f4f7]", text: "text-[#6b7785]", dot: "bg-[#6b7785]" };
        const errorTone: Tone = { bg: "bg-[#fff2f0]", text: "text-[#f53f3f]", dot: "bg-[#f53f3f]" };
        const infoTone: Tone = { bg: "bg-blue-50", text: "text-blue-500", dot: "bg-blue-500" };

        let label: string | null = null;
        let tone: Tone = neutralTone;

        if (approvalLabel) {
            label = approvalLabel;
            tone = isKnowledgeApprovalRejected(file) ? errorTone : infoTone;
        } else {
            const config: Record<string, { label: string; tone: Tone }> = {
                [FileStatus.UPLOADING]: { label: localize("com_knowledge.uploading_status"), tone: neutralTone },
                [FileStatus.PROCESSING]: { label: localize("com_knowledge.parsing_status"), tone: neutralTone },
                [FileStatus.WAITING]: { label: localize("com_knowledge.queueing_status"), tone: neutralTone },
                [FileStatus.REBUILDING]: { label: localize("com_knowledge.rebuilding_status"), tone: neutralTone },
                [FileStatus.FAILED]: { label: localize("com_knowledge.fail"), tone: errorTone },
                [FileStatus.TIMEOUT]: { label: localize("com_knowledge.timeout"), tone: errorTone },
                [FileStatus.VIOLATION]: { label: localize("com_knowledge.violation"), tone: errorTone },
            };
            const item = file.status ? config[file.status] : undefined;
            if (!item) return null;
            label = item.label;
            tone = item.tone;
        }

        if (!label) return null;

        const pill = (
            <div className={cn("inline-flex items-center justify-center gap-1 rounded-[4px] px-2", tone.bg)}>
                <span className={cn("size-1 shrink-0 rounded-full", tone.dot)} />
                <span className={cn("whitespace-nowrap text-xs leading-5", tone.text)}>{label}</span>
            </div>
        );

        const wrapped = statusReason ? (
            <Tooltip>
                <TooltipTrigger asChild>
                    <span className="inline-flex">{pill}</span>
                </TooltipTrigger>
                <TooltipContent noArrow side="top" className="max-w-[320px] rounded-md bg-[#1D2129] px-3 py-2 text-left text-xs leading-5 text-white">
                    {statusReason}
                </TooltipContent>
            </Tooltip>
        ) : pill;

        // Inline (H5 row meta line) returns the bare pill; desktop card overlays it on the icon.
        return inline ? wrapped : (
            <div className="absolute bottom-1 left-1 z-10">{wrapped}</div>
        );
    };

    // Similar-document tag — placed in the SAME slot as the status tag: overlaid on the
    // icon for the desktop card, inline after the name for the H5 row. The two never
    // co-occur (similar only shows on SUCCESS files, the status tag only on non-success).
    const renderSimilarTag = (overlay = false) => {
        if (!(versionManagementEnabled && canManageMembers && file.has_similar && !file.is_multi_version && file.status === FileStatus.SUCCESS)) {
            return null;
        }
        const btn = (
            <button
                type="button"
                onClick={(e) => {
                    e.stopPropagation();
                    onOpenVersionManagement?.(file);
                }}
                className="flex h-5 shrink-0 items-center gap-1 rounded bg-[#FFF3E8] px-1.5 text-xs text-[#F76F44] hover:bg-[#FFE6D2]"
            >
                <FileSearch className="size-3" />
                {localize("com_knowledge.version.pill_similar")}
            </button>
        );
        return overlay ? <div className="absolute bottom-1 left-1 z-10">{btn}</div> : btn;
    };

    const getStatusText = () => {
        if (isRenaming) {
            return (
                <div className="flex-1 min-w-0 pr-1">
                    <input
                        ref={inputRef}
                        type="text"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onBlur={handleRenameSubmit}
                        onKeyDown={handleKeyDown}
                        onClick={(e) => e.stopPropagation()}
                        className="w-full h-6 px-1.5 text-sm border border-[#DDDDDD] rounded outline-none shadow-[0_0_0_2px_#F1F5F9] bg-white font-normal"
                    />
                </div>
            );
        }

        return (
            <div className="flex min-w-0 items-start gap-1.5">
                {versionManagementEnabled && file.is_multi_version && file.version_no != null && file.version_no >= 1 && (
                    <span className="mt-0.5 flex h-5 shrink-0 items-center justify-center rounded bg-blue-50 px-1.5 text-xs font-medium text-blue-500">
                        {`V${file.version_no}`}
                    </span>
                )}
                <span
                    className={cn(
                        "line-clamp-2 min-h-[40px] min-w-0 break-all leading-5",
                        nameToneClass,
                    )}
                >
                    {renderHighlightedName(file.name, highlightKeyword)}
                </span>
            </div>
        );
    };

    const handleCardClick = () => {
        if (isCreating || isRenaming || isUploadingFolderPlaceholder) return;
        // Folder click is treated as "enter folder"/"navigate directory"
        // (depending on the parent component's onNavigateFolder implementation).
        if (isFolder) {
            onNavigateFolder?.(file.id);
            return;
        }

        if (pendingUpload) {
            onPreviewPendingUpload?.(pendingUpload.requestId);
            return;
        }
        if (!isKnowledgeItemPreviewable(file)) return;

        // Space square drawer sets disableClickNavigate to avoid relying on default navigation;
        // still honor explicit onPreview when provided.
        if (disableClickNavigate && !onPreview) return;
        onPreview?.(file.id);
    };

    const hasRetryOption = Boolean(
        onRetry && (
            file.status === FileStatus.FAILED ||
            file.status === FileStatus.VIOLATION ||
            (isFolder && file.hasFailedFiles === true)
        )
    );
    // Version row actions visible for this file (parsed non-folder for management; multi-version for history).
    const showVersionManagement = versionManagementEnabled && !isFolder && file.status === FileStatus.SUCCESS && isAdmin && Boolean(onOpenVersionManagement);
    const showVersionHistory = versionManagementEnabled && !isFolder && Boolean(file.is_multi_version) && Boolean(onOpenVersionHistory);
    const showMoveItem = Boolean(onMove) && !isCreating;
    const showMenuDownloadItem = canDownload && !hideDownloadActions;
    // Card view puts EVERY action behind the ⋮ menu, even a lone one, so a card
    // never sprouts a second floating control over its thumbnail. That includes
    // the approval decisions, which used to sit inline. The H5 row keeps its own
    // inline 同意/拒绝 (it has the width and no thumbnail to cover), so the
    // pending branch is card-only.
    const showPendingMenuItems = Boolean(pendingUpload) && !mobileListMode
        && (canDecidePending || canWithdrawPending);
    const hasReviewedMenuItems = showMenuDownloadItem || isAdmin || canRename || canDelete
        || Boolean(onManagePermission) || showMoveItem || showVersionManagement || showVersionHistory;
    // Placeholder has only a temp id (no backend identity) — suppress all row actions.
    const showMoreMenu = !isUploadingFolderPlaceholder
        && (pendingUpload ? showPendingMenuItems : hasReviewedMenuItems);
    const showCardActions = moreMenuOpen || hovered;
    const cardOpensPreviewOrFolder =
        !isCreating &&
        !isRenaming &&
        !isUploadingFolderPlaceholder &&
        (Boolean(pendingUpload) || isFolder || isKnowledgeItemPreviewable(file));

    // A pending upload is not a real file yet: the only things that apply are the
    // approval decisions, so its menu replaces the ordinary file actions.
    const pendingMenuItems = pendingUpload && (
        <>
            {canDecidePending && onDecidePendingUpload && (
                <ActionMenuItem
                    className="text-success data-[highlighted]:text-success focus:text-success"
                    disabled={pendingUploadDeciding}
                    onClick={(e) => { e.stopPropagation(); onDecidePendingUpload(pendingUpload.requestId, "approve"); }}
                    icon={<Outlined.Check className="text-success" />}
                    // 同意 (not 审批中心's 通过) per the pending-upload design (Figma 13198:78124).
                    label={localize("com_approval.action_approve")}
                />
            )}
            {canDecidePending && onDecidePendingUpload && (
                <ActionMenuItem
                    danger
                    disabled={pendingUploadDeciding}
                    onClick={(e) => { e.stopPropagation(); onDecidePendingUpload(pendingUpload.requestId, "reject"); }}
                    icon={<Outlined.Close />}
                    label={localize("com_approval.action_reject")}
                />
            )}
            {canWithdrawPending && onWithdrawPendingUpload && (
                <ActionMenuItem
                    danger
                    disabled={pendingUploadDeciding}
                    onClick={(e) => { e.stopPropagation(); onWithdrawPendingUpload(pendingUpload.requestId); }}
                    icon={<Outlined.Delete />}
                    label={localize("com_knowledge.delete")}
                />
            )}
        </>
    );

    // Shared action-menu items, reused by the "..." dropdown and the right-click menu.
    const reviewedMenuItems = (
        <>
            {showMenuDownloadItem && (
                <ActionMenuItem
                    onClick={(e) => { e.stopPropagation(); onDownload(); }}
                    icon={<Outlined.Download />}
                    label={localize("com_knowledge.download")}
                />
            )}
            {onManagePermission && (
                <ActionMenuItem
                    onClick={(e) => { e.stopPropagation(); onManagePermission(); }}
                    icon={<Outlined.PeopleSafe />}
                    label={localize("com_permission.manage_permission")}
                />
            )}
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

    const moreMenuItems = showPendingMenuItems ? pendingMenuItems : reviewedMenuItems;

    const handleCardContextMenu = (e: MouseEvent<HTMLDivElement>) => {
        if (!showMoreMenu) return;
        e.preventDefault();
        // Same lazy permission resolution as the "..." trigger, otherwise the
        // right-click menu renders with unresolved (reduced) permissions.
        onEnsureFilePermissions?.(file);
        setContextMenuPosition({ x: e.clientX, y: e.clientY });
        setContextMenuOpen(true);
    };

    // H5 mobile list row: flat row (no border / shadow / card background) with
    // icon + title + date + tags, and a circular checkbox on the far right.
    // Rendered independently from the desktop card so the desktop path is untouched.
    if (mobileListMode) {
        const mobileStatusPill = renderStatusOverlayTag(true);
        const mobileSimilarTag = renderSimilarTag();
        return (
            <div
                className={cn(
                    // Full-bleed row: the list container has no horizontal padding on mobile,
                    // so the row's own px-4 gives the 16px content gutter while the selected
                    // background spans the full width.
                    "flex items-center gap-2 px-4 py-3",
                    cardOpensPreviewOrFolder ? "cursor-pointer" : "cursor-default",
                )}
                style={
                    isSelected
                        ? { background: "linear-gradient(0deg, rgb(var(--brand-500)/0.07) 0%, rgb(var(--brand-500)/0.07) 100%), #FFF" }
                        : undefined
                }
                onClick={handleCardClick}
            >
                {/* File icon 48x48 — colored icons render without backdrop on H5 */}
                <div className="relative flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-md">
                    <FileIconRenderer file={file} isFolder={isFolder} iconClassName="size-12 shrink-0" thumbBordered transparentBg />
                </div>

                {/* Text block: title (+ status) / (date + tags) */}
                <div className="flex min-w-0 flex-1 flex-col">
                    {isRenaming ? (
                        <input
                            ref={inputRef}
                            type="text"
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onBlur={handleRenameSubmit}
                            onKeyDown={handleKeyDown}
                            onClick={(e) => e.stopPropagation()}
                            className="h-6 w-full rounded border border-[#DDDDDD] bg-white px-1.5 text-sm font-normal shadow-[0_0_0_2px_#F1F5F9] outline-none"
                        />
                    ) : (
                        <div className="flex min-w-0 items-center gap-1.5">
                            <span className={cn("min-w-0 truncate text-sm leading-5", nameToneClass)}>
                                {renderHighlightedName(file.name, highlightKeyword)}
                            </span>
                            {mobileStatusPill && (
                                <span className="inline-flex shrink-0 items-center self-center leading-5">
                                    {mobileStatusPill}
                                </span>
                            )}
                            {mobileSimilarTag && (
                                <span className="inline-flex shrink-0 items-center self-center leading-5">
                                    {mobileSimilarTag}
                                </span>
                            )}
                        </div>
                    )}

                    {/* Date + tags on a single line */}
                    <div className="mt-1 flex min-w-0 items-center gap-1.5 overflow-hidden">
                        <span className="shrink-0 text-xs leading-5 text-text-3 tabular-nums">
                            {formatTimeCard(file.updatedAt)}
                        </span>
                        {!isFolder && file.tags && file.tags.length > 0 && (
                            <>
                                <span className="mx-0.5 h-2.5 w-px shrink-0 bg-[#E0E0E0]" aria-hidden />
                                <TagGroup
                                    tags={file.tags}
                                    variant="text-h5"
                                    highlightedTagIds={highlightedTagIds}
                                />
                            </>
                        )}
                    </div>
                </div>

                {pendingUpload && (canDecidePending || canWithdrawPending) && (
                    <PendingUploadApprovalActions
                        requestId={pendingUpload.requestId}
                        disabled={pendingUploadDeciding}
                        onDecide={canDecidePending ? onDecidePendingUpload : undefined}
                        onWithdraw={canWithdrawPending ? onWithdrawPendingUpload : undefined}
                    />
                )}

                {/* Circular selection checkbox on the far right */}
                {!hideSelectionCheckbox && (
                    <RoundCheckbox
                        className="shrink-0"
                        checked={isSelected}
                        disabled={!isSelectable}
                        onCheckedChange={(checked) => onSelect(checked)}
                    />
                )}
            </div>
        );
    }

    return (
        <Card
            draggable={!pendingUpload && cardDraggable && !isCreating && !isUploading}
            onDragStart={cardDraggable ? onCardDragStart : undefined}
            onDragOver={isFolder && !isUploadingFolderPlaceholder ? onFolderDragOver : undefined}
            onDragLeave={isFolder && !isUploadingFolderPlaceholder ? onFolderDragLeave : undefined}
            onDrop={isFolder && !isUploadingFolderPlaceholder ? onFolderDrop : undefined}
            className={cn(
                "group relative rounded-md overflow-hidden border-[0.5px] p-0 gap-0 py-0 shadow-none max-[767px]:rounded-md",
                !mobileListMode && "h-[160px]",
                cardOpensPreviewOrFolder ? "cursor-pointer" : "cursor-default",
                isSelected
                    ? "bg-blue-50"
                    : isNotParsed
                      ? "bg-[#fbfbfb]"
                      : "bg-white",
                isSelected
                    ? "border-border-base shadow-[0_4px_20px_0_rgba(0,17,147,0.05)]"
                    : "border-border-base hover:border-border-deep",
                hovered && "shadow-[0_4px_20px_0_rgba(0,17,147,0.05)]",
                // F034: highlight a folder card as the drop target — card border only
                isFolderDragOver && "border-primary"
            )}
            style={{
                transitionProperty: 'background-color, box-shadow, border-color',
                transitionDuration: '350ms',
                transitionTimingFunction: 'ease-in-out',
                ...(isSelected
                    ? { backgroundColor: 'rgb(var(--brand-500)/0.07)' }
                    : isNotParsed
                        ? { backgroundColor: '#fbfbfb' }
                        : {}),
            }}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            onClick={handleCardClick}
            onContextMenu={handleCardContextMenu}
        >
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
                    <ActionMenuContent align="start" width={140} onClick={(e) => e.stopPropagation()}>
                        {moreMenuItems}
                    </ActionMenuContent>
                </DropdownMenu>
            )}
            <CardContent className={cn(
                "flex flex-col p-0",
                !mobileListMode && "h-full",
                mobileListMode && "max-[767px]:flex-row max-[767px]:items-center max-[767px]:gap-2 max-[767px]:p-1"
            )}>
                {/* Uploading-folder scrim: 50% white mask over the whole card so it reads
                    as "in progress". The "上传中" status tag sits above it (z-20). */}
                {isUploadingFolderPlaceholder && (
                    <div className="pointer-events-none absolute inset-0 z-10 bg-white/50" />
                )}
                {!hideSelectionCheckbox && mobileListMode && (
                    <div className="hidden max-[767px]:flex max-[767px]:shrink-0 max-[767px]:items-center max-[767px]:justify-center max-[767px]:pl-1 max-[767px]:pr-0.5">
                        <Checkbox
                            className={cn(
                                SELECTION_CHECKBOX_CLASS,
                                !isSelectable && "cursor-not-allowed opacity-50",
                            )}
                            disabled={!isSelectable}
                            checked={isSelected}
                            onCheckedChange={(checked) => onSelect(!!checked)}
                            onPointerDown={(e) => e.stopPropagation()}
                            onMouseDown={(e) => e.stopPropagation()}
                            onClick={(e) => e.stopPropagation()}
                        />
                    </div>
                )}
                {/* Thumbnail / icon area — flexes to fill the remaining space under
                    the 160px fixed-height card, leaving the bottom info row at its natural height. */}
                <div className={cn(
                    "relative flex min-h-0 flex-1 p-1.5",
                    mobileListMode && "max-[767px]:h-12 max-[767px]:w-12 max-[767px]:flex-none max-[767px]:p-0 max-[767px]:rounded-[4px]",
                )}>
                    <div className={cn(
                        "relative flex flex-1 items-center justify-center overflow-hidden rounded-[4px]",
                        isSelected
                            ? "bg-transparent"
                            : isNotParsed
                                ? "bg-[#fbfbfb]"
                                : "bg-white",
                        mobileListMode && "max-[767px]:rounded-[4px]",
                    )}>
                        <FileIconRenderer file={file} isFolder={isFolder} />
                        {renderStatusOverlayTag()}
                        {renderSimilarTag(true)}
                    </div>

                    {!hideSelectionCheckbox && (
                        <div
                            className={cn(
                                "absolute left-2 top-2 z-10 transition-opacity",
                                mobileListMode && "max-[767px]:hidden",
                                !revealCardActionsOnHoverOnly
                                    ? "opacity-100"
                                    : isSelected
                                    ? "opacity-100"
                                    : "opacity-0 group-hover:opacity-100"
                            )}
                        >
                            <Checkbox
                                className={cn(
                                    SELECTION_CHECKBOX_CLASS,
                                    !isSelectable && "cursor-not-allowed opacity-50",
                                )}
                                disabled={!isSelectable}
                                checked={isSelected}
                                onCheckedChange={(checked) => onSelect(!!checked)}
                                onPointerDown={(e) => e.stopPropagation()}
                                onMouseDown={(e) => e.stopPropagation()}
                                onClick={(e) => e.stopPropagation()}
                            />
                        </div>
                    )}

                    {!mobileListMode && (
                        <div
                            className={cn(
                                "absolute right-2 top-2 z-20 flex items-center gap-1 transition-opacity",
                                !revealCardActionsOnHoverOnly
                                    ? "pointer-events-auto opacity-100"
                                    : showCardActions
                                    ? "pointer-events-auto opacity-100"
                                    : "pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100"
                            )}
                        >
                            {showMoreMenu && (
                                <DropdownMenu open={moreMenuOpen} onOpenChange={handleMoreMenuOpenChange}>
                                    <DropdownMenuTrigger asChild>
                                        <Button
                                            variant="outline"
                                            size="icon"
                                            className="w-5 h-5 rounded-md shrink-0"
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            <MoreVertical className="size-4 text-text-2 group-hover:text-text-1" />
                                        </Button>
                                    </DropdownMenuTrigger>

                                    <ActionMenuContent
                                        align="end"
                                        width={140}
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        {moreMenuItems}
                                    </ActionMenuContent>
                                </DropdownMenu>
                            )}
                        </div>
                    )}
                </div>

                {/* Bottom info area */}
                <div className={cn(
                    "flex flex-col gap-1 px-2 py-1.5",
                    mobileListMode && "max-[767px]:min-w-0 max-[767px]:flex-1 max-[767px]:gap-0 max-[767px]:p-0 max-[767px]:pr-1",
                )}>
                    {/* File name + status */}
                    <div className="flex min-w-0 text-xs font-medium">
                        {getStatusText()}
                    </div>

                    {/* Footer (tags + time) */}
                    <div className="flex min-w-0 items-center justify-between gap-2">
                        <div className="flex min-h-[20px] min-w-0 flex-1 items-center">
                            {(!isFolder && file.tags && file.tags.length > 0) && (
                                <TagGroup tags={file.tags} variant="text" highlightedTagIds={highlightedTagIds} />
                            )}
                        </div>
                        <span className="shrink-0 text-caption-sm leading-5 text-text-3 tabular-nums">{formatTimeCard(file.updatedAt)}</span>
                    </div>
                </div>

                {mobileListMode && (
                    <div
                        className={cn(
                            "flex shrink-0 items-center gap-1 pr-1 transition-opacity",
                            !revealCardActionsOnHoverOnly
                                ? "pointer-events-auto opacity-100"
                                : showCardActions
                                  ? "pointer-events-auto opacity-100"
                                  : "pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100",
                        )}
                    >
                    {showMenuDownloadItem && (
                        <Button
                            variant="outline"
                            size="icon"
                            className="h-5 w-5 shrink-0 rounded-md hover:bg-gray-100"
                            onClick={(e) => { e.stopPropagation(); onDownload(); }}
                            title={localize("com_knowledge.download")}
                        >
                            <Download className="size-3.5 text-text-2" />
                        </Button>
                    )}
                    {showMoreMenu && (
                        <DropdownMenu open={moreMenuOpen} onOpenChange={handleMoreMenuOpenChange}>
                            <DropdownMenuTrigger asChild>
                                <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-5 w-5 shrink-0 rounded-md"
                                    onClick={(e) => e.stopPropagation()}
                                >
                                    <MoreVertical className="size-4 text-text-2" />
                                </Button>
                            </DropdownMenuTrigger>
                            <ActionMenuContent
                                align="end"
                                onClick={(e) => e.stopPropagation()}
                            >
                                {showMenuDownloadItem && (
                                    <ActionMenuItem
                                        onClick={(e) => { e.stopPropagation(); onDownload(); }}
                                        icon={<Outlined.Download />}
                                        label={localize("com_knowledge.download")}
                                    />
                                )}
                                {onManagePermission && (
                                    <ActionMenuItem
                                        onClick={(e) => { e.stopPropagation(); onManagePermission(); }}
                                        icon={<Outlined.PeopleSafe />}
                                        label={localize("com_permission.manage_permission")}
                                    />
                                )}
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
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            if (!fileChangeLock.locked) startRenaming();
                                        }}
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
                            </ActionMenuContent>
                        </DropdownMenu>
                    )}
                    </div>
                )}
            </CardContent>
        </Card>
    );
}
