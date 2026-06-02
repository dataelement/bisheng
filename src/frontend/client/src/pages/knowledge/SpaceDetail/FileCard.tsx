import { Download, Edit, MoreVertical, RefreshCw, Shield, Tag, Trash2, X } from "lucide-react";
import { useState } from "react";
import { FileStatus, FileType, KnowledgeFile, SpaceRole } from "~/api/knowledge";
import { Button, Checkbox } from "~/components";
import { Card, CardContent } from "~/components/ui/Card";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import { knowledgeSpaceDropdownSurfaceClassName } from "~/components/SidebarListMoreMenu";
import { cn } from "~/utils";
import FileIconRenderer from "./FileIcon";
import TagGroup from "./TagGroup";
import { useInlineRename } from "../hooks/useInlineRename";
import { formatTimeCard, getKnowledgeApprovalStatusLabel, isKnowledgeApprovalRejected, isKnowledgeItemPreviewable } from "../knowledgeUtils";
import { useLocalize, useMediaQuery } from "~/hooks";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";

interface FileCardProps {
    file: KnowledgeFile;
    userRole: SpaceRole;
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
    canRename?: boolean;
    canDelete?: boolean;
    canDownload?: boolean;
    disableClickNavigate?: boolean;
    hideSelectionCheckbox?: boolean;
    /** H5: render as list-row (not card tile). */
    mobileListMode?: boolean;
    /** Hide per-file download UI (icon + menu item), e.g. in read-only preview drawers. */
    hideDownloadActions?: boolean;
}

export function FileCard({
    file,
    userRole,
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
    canRename = false,
    canDelete = false,
    canDownload = false,
    disableClickNavigate = false,
    hideSelectionCheckbox = false,
    mobileListMode = false,
    hideDownloadActions = false,
}: FileCardProps) {
    const localize = useLocalize();
    /** True when primary input is mouse + hover: actions reveal on card hover. Touch / coarse pointer: keep actions visible (viewport width does not matter). */
    const revealCardActionsOnHoverOnly = useMediaQuery(
        "(hover: hover) and (pointer: fine)",
    );
    const isCreating = !!file.isCreating;
    const [hovered, setHovered] = useState(false);
    const [moreMenuOpen, setMoreMenuOpen] = useState(false);
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

    const nameToneClass = isKnowledgeItemPreviewable(file)
        ? "text-[#212121]"
        : "text-[#999]";

    /**
     * Status pill overlaid on the bottom-left of the preview area (Figma 11671:34497).
     * Covers all non-success states: parsing-like (neutral grey) + error / approval (colored).
     */
    const renderStatusOverlayTag = () => {
        if (!isAdmin || isFolder) return null;
        if (file.status === FileStatus.SUCCESS) return null;

        const approvalLabel = approvalStatusLabel;
        const statusReason = failureMessage || approvalReason;

        type Tone = { bg: string; text: string; dot: string };
        const neutralTone: Tone = { bg: "bg-[#f2f4f7]", text: "text-[#6b7785]", dot: "bg-[#6b7785]" };
        const errorTone: Tone = { bg: "bg-[#fff2f0]", text: "text-[#f53f3f]", dot: "bg-[#f53f3f]" };
        const infoTone: Tone = { bg: "bg-[#e8f3ff]", text: "text-[#165dff]", dot: "bg-[#165dff]" };

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
            <div className={cn("inline-flex items-center gap-1 rounded-[4px] px-2 py-0.5", tone.bg)}>
                <span className={cn("size-1 shrink-0 rounded-full", tone.dot)} />
                <span className={cn("text-xs leading-5", tone.text)}>{label}</span>
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

        return (
            <div className="absolute bottom-1 left-1 z-10">{wrapped}</div>
        );
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
                        className="w-full h-6 px-1.5 text-sm border border-[#165dff] rounded outline-none shadow-[0_0_0_2px_rgba(22,93,255,0.2)] bg-white font-normal"
                    />
                </div>
            );
        }

        return (
            <span
                className={cn(
                    "line-clamp-2 min-h-[40px] break-all leading-5",
                    nameToneClass,
                )}
            >
                {file.name}
            </span>
        );
    };

    const handleCardClick = () => {
        if (isCreating || isRenaming) return;
        // Folder click is treated as "enter folder"/"navigate directory"
        // (depending on the parent component's onNavigateFolder implementation).
        if (isFolder) {
            onNavigateFolder?.(file.id);
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
            (isFolder && file.successFileNum !== undefined && file.fileNum !== undefined && file.successFileNum < file.fileNum)
        )
    );
    const showMoreMenu = canDownload || isAdmin || canRename || canDelete || Boolean(onManagePermission);
    /** 有「更多」时下载只在菜单内；无更多（普通成员/预览）时单独显示下载图标 */
    const showInlineDownloadButton = canDownload && !hideDownloadActions && !showMoreMenu;
    const showMenuDownloadItem = canDownload && !hideDownloadActions;
    const showCardActions = moreMenuOpen || hovered;
    const cardOpensPreviewOrFolder =
        !isCreating &&
        !isRenaming &&
        (isFolder || isKnowledgeItemPreviewable(file));

    return (
        <Card
            className={cn(
                "group rounded-[6px] overflow-hidden border-[0.5px] p-0 gap-0 py-0 shadow-none max-[767px]:rounded-[6px]",
                cardOpensPreviewOrFolder ? "cursor-pointer" : "cursor-default",
                isSelected
                    ? "bg-[rgba(230,237,252,0.3)]"
                    : isNotParsed
                        ? "bg-[#fbfbfb]"
                        : "bg-white",
                isSelected
                    ? "border-[#ECECEC] shadow-[0_4px_20px_0_rgba(0,17,147,0.05)]"
                    : "border-[#ECECEC] hover:border-[#c9cdd4]",
                hovered && "shadow-[0_4px_20px_0_rgba(0,17,147,0.05)]"
            )}
            style={{
                transitionProperty: 'background-color, box-shadow, border-color',
                transitionDuration: '350ms',
                transitionTimingFunction: 'ease-in-out',
                ...(isSelected
                    ? { backgroundColor: 'rgba(230,237,252,0.3)' }
                    : isNotParsed
                        ? { backgroundColor: '#fbfbfb' }
                        : {}),
            }}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            onClick={handleCardClick}
        >
            <CardContent className={cn(
                "flex flex-col p-0",
                mobileListMode && "max-[767px]:flex-row max-[767px]:items-center max-[767px]:gap-2 max-[767px]:p-1"
            )}>
                {!hideSelectionCheckbox && mobileListMode && (
                    <div className="hidden max-[767px]:flex max-[767px]:shrink-0 max-[767px]:items-center max-[767px]:justify-center max-[767px]:pl-1 max-[767px]:pr-0.5">
                        <Checkbox
                            className={isSelected ? "border-primary" : "border-gray-400"}
                            checked={isSelected}
                            onCheckedChange={(checked) => onSelect(!!checked)}
                            onPointerDown={(e) => e.stopPropagation()}
                            onMouseDown={(e) => e.stopPropagation()}
                            onClick={(e) => e.stopPropagation()}
                        />
                    </div>
                )}
                {/* Thumbnail / icon area */}
                <div className={cn(
                    "relative flex h-[106px] shrink-0 p-1",
                    mobileListMode && "max-[767px]:h-12 max-[767px]:w-12 max-[767px]:p-0 max-[767px]:rounded-[4px]",
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
                                className={isSelected ? "border-primary" : "border-gray-400"}
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
                            {showInlineDownloadButton && (
                                <Button
                                    variant="outline"
                                    size="icon"
                                    className="w-5 h-5 rounded-md hover:bg-gray-100 shrink-0"
                                    onClick={(e) => { e.stopPropagation(); onDownload(); }}
                                    title={localize("com_knowledge.download")}
                                >
                                    <Download className="size-3.5 text-[#4e5969] group-hover:text-[#1d2129]" />
                                </Button>
                            )}
                            {showMoreMenu && (
                                <DropdownMenu open={moreMenuOpen} onOpenChange={setMoreMenuOpen}>
                                    <DropdownMenuTrigger asChild>
                                        <Button
                                            variant="outline"
                                            size="icon"
                                            className="w-5 h-5 rounded-md shrink-0"
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            <MoreVertical className="size-4 text-[#4e5969] group-hover:text-[#1d2129]" />
                                        </Button>
                                    </DropdownMenuTrigger>

                                    <DropdownMenuContent
                                        align="end"
                                        className={cn("min-w-[120px]", knowledgeSpaceDropdownSurfaceClassName)}
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        {showMenuDownloadItem && (
                                            <DropdownMenuItem
                                                onClick={(e) => { e.stopPropagation(); onDownload(); }}
                                                className="flex items-center"
                                            >
                                                <Download className="mr-2 size-4 shrink-0" />
                                                {localize("com_knowledge.download")}
                                            </DropdownMenuItem>
                                        )}

                                        {onManagePermission && (
                                            <DropdownMenuItem
                                                onClick={(e) => { e.stopPropagation(); onManagePermission(); }}
                                                className="flex items-center"
                                            >
                                                <Shield className="mr-2 size-4 shrink-0" />
                                                {localize("com_permission.manage_permission")}
                                            </DropdownMenuItem>
                                        )}

                                        {isAdmin && !isFolder && (
                                            <DropdownMenuItem
                                                onClick={(e) => { e.stopPropagation(); onEditTags(); }}
                                                className="flex items-center"
                                            >
                                                <Tag className="mr-2 size-4 shrink-0" />
                                                {localize("com_knowledge.edit_tags")}
                                            </DropdownMenuItem>
                                        )}
                                        {canRename && (
                                            <DropdownMenuItem
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    startRenaming();
                                                }}
                                                className="flex items-center"
                                            >
                                                <Edit className="mr-2 size-4 shrink-0" />
                                                {localize("com_knowledge.rename")}
                                            </DropdownMenuItem>
                                        )}
                                        {isAdmin && hasRetryOption && (
                                            <DropdownMenuItem
                                                onClick={(e) => { e.stopPropagation(); onRetry?.(); }}
                                                className="flex items-center"
                                            >
                                                <RefreshCw className="mr-2 size-4 shrink-0" />
                                                {localize("com_knowledge.retry")}
                                            </DropdownMenuItem>
                                        )}
                                        {canDelete && (
                                            <DropdownMenuItem
                                                onClick={(e) => { e.stopPropagation(); onDelete(); }}
                                                className="flex items-center text-[#f53f3f] focus:text-[#f53f3f]"
                                            >
                                                <Trash2 className="mr-2 size-4 shrink-0" />
                                                {localize("com_knowledge.delete")}
                                            </DropdownMenuItem>
                                        )}
                                    </DropdownMenuContent>
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

                    {/* Footer (tags / count + time) */}
                    <div className="flex min-w-0 items-center justify-between gap-2">
                        <div className="flex min-h-[20px] min-w-0 flex-1 items-center">
                            {isAdmin && isFolder && file.fileNum != null && (
                                <span className="whitespace-nowrap text-[10px] leading-5 text-[#999] tabular-nums">
                                    {localize("com_knowledge_items_count", { count: file.fileNum ?? 0 })}
                                </span>
                            )}
                            {!isAdmin && isFolder && file.fileNum != null && (
                                <span className="whitespace-nowrap text-[10px] leading-5 text-[#999] tabular-nums">
                                    {localize("com_knowledge_items_count", { count: file.successFileNum ?? 0 })}
                                </span>
                            )}
                            {(!isFolder && file.tags && file.tags.length > 0) && (
                                <TagGroup tags={file.tags} />
                            )}
                        </div>
                        <span className="shrink-0 text-[10px] leading-5 text-[#999] tabular-nums">{formatTimeCard(file.updatedAt)}</span>
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
                            <Download className="size-3.5 text-[#4e5969]" />
                        </Button>
                    )}
                    {showMoreMenu && (
                        <DropdownMenu open={moreMenuOpen} onOpenChange={setMoreMenuOpen}>
                            <DropdownMenuTrigger asChild>
                                <Button
                                    variant="outline"
                                    size="icon"
                                    className="h-5 w-5 shrink-0 rounded-md"
                                    onClick={(e) => e.stopPropagation()}
                                >
                                    <MoreVertical className="size-4 text-[#4e5969]" />
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                                align="end"
                                className={cn("min-w-[120px]", knowledgeSpaceDropdownSurfaceClassName)}
                                onClick={(e) => e.stopPropagation()}
                            >
                                        {showMenuDownloadItem && (
                                            <DropdownMenuItem
                                                onClick={(e) => { e.stopPropagation(); onDownload(); }}
                                                className="flex items-center"
                                            >
                                        <Download className="mr-2 size-4 shrink-0" />
                                                {localize("com_knowledge.download")}
                                            </DropdownMenuItem>
                                        )}

                                {onManagePermission && (
                                    <DropdownMenuItem
                                        onClick={(e) => { e.stopPropagation(); onManagePermission(); }}
                                        className="flex items-center"
                                    >
                                        <Shield className="mr-2 size-4 shrink-0" />
                                        {localize("com_permission.manage_permission")}
                                    </DropdownMenuItem>
                                )}

                                {isAdmin && !isFolder && (
                                    <DropdownMenuItem
                                        onClick={(e) => { e.stopPropagation(); onEditTags(); }}
                                        className="flex items-center"
                                    >
                                        <Tag className="mr-2 size-4 shrink-0" />
                                        {localize("com_knowledge.edit_tags")}
                                    </DropdownMenuItem>
                                )}
                                {canRename && (
                                    <DropdownMenuItem
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            startRenaming();
                                        }}
                                        className="flex items-center"
                                    >
                                        <Edit className="mr-2 size-4 shrink-0" />
                                        {localize("com_knowledge.rename")}
                                    </DropdownMenuItem>
                                )}
                                {isAdmin && hasRetryOption && (
                                    <DropdownMenuItem
                                        onClick={(e) => { e.stopPropagation(); onRetry?.(); }}
                                        className="flex items-center"
                                    >
                                        <RefreshCw className="mr-2 size-4 shrink-0" />
                                        {localize("com_knowledge.retry")}
                                    </DropdownMenuItem>
                                )}
                                {canDelete && (
                                    <DropdownMenuItem
                                        onClick={(e) => { e.stopPropagation(); onDelete(); }}
                                        className="flex items-center text-[#f53f3f] focus:text-[#f53f3f]"
                                    >
                                        <Trash2 className="mr-2 size-4 shrink-0" />
                                        {localize("com_knowledge.delete")}
                                    </DropdownMenuItem>
                                )}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}
                    </div>
                )}
            </CardContent>
        </Card>
    );
}
