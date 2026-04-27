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
        file.status === FileStatus.FAILED || file.status === FileStatus.TIMEOUT
    ) && file.errorMessage?.trim()
        ? file.errorMessage.trim()
        : null;
    const approvalStatusLabel = getKnowledgeApprovalStatusLabel(file);
    const approvalReason = file.approvalReason?.trim() || null;

    const isAdmin = userRole === SpaceRole.CREATOR || userRole === SpaceRole.ADMIN;
    const isFolder = file.type === FileType.FOLDER;

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

    const renderStatusBadge = () => {
        if (!isAdmin || isFolder) return null;

        const approvalLabel = approvalStatusLabel;
        const statusReason = failureMessage || approvalReason;

        let badge: React.ReactNode = null;
        if (approvalLabel) {
            const rejected = isKnowledgeApprovalRejected(file);
            badge = (
                <span
                    className={cn(
                        "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm px-2 py-0.5 text-xs font-medium",
                        rejected ? "bg-[#fff2f0] text-[#f53f3f]" : "bg-[#e8f3ff] text-[#165dff]",
                    )}
                >
                    <span className={cn("size-1.5 shrink-0 rounded-full", rejected ? "bg-[#f53f3f]" : "bg-[#165dff]")} />
                    {approvalLabel}
                </span>
            );
        } else {
            const config: Record<string, { label: string; color: string; bg: string; dot: string }> = {
                [FileStatus.UPLOADING]: { label: localize("com_knowledge.uploading_status"), color: "text-[#165dff]", bg: "bg-[#e8f3ff]", dot: "bg-[#165dff]" },
                [FileStatus.PROCESSING]: { label: localize("com_knowledge.parsing_status"), color: "text-[#165dff]", bg: "bg-[#e8f3ff]", dot: "bg-[#165dff]" },
                [FileStatus.WAITING]: { label: localize("com_knowledge.queueing_status"), color: "text-[#165dff]", bg: "bg-[#e8f3ff]", dot: "bg-[#165dff]" },
                [FileStatus.REBUILDING]: { label: localize("com_knowledge.rebuilding_status"), color: "text-[#165dff]", bg: "bg-[#e8f3ff]", dot: "bg-[#165dff]" },
                [FileStatus.FAILED]: { label: localize("com_knowledge.fail"), color: "text-[#f53f3f]", bg: "bg-[#fff2f0]", dot: "bg-[#f53f3f]" },
                [FileStatus.TIMEOUT]: { label: localize("com_knowledge.timeout"), color: "text-[#f53f3f]", bg: "bg-[#fff2f0]", dot: "bg-[#f53f3f]" },
            };
            const item = config[file.status];
            if (!item) return null;
            badge = (
                <span
                    className={cn(
                        "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm px-2 py-0.5 text-xs font-medium",
                        item.bg,
                        item.color,
                    )}
                >
                    <span className={cn("size-1.5 shrink-0 rounded-full", item.dot)} />
                    {item.label}
                </span>
            );
        }

        if (!badge) return null;
        if (!statusReason) return badge;

        return (
            <Tooltip>
                <TooltipTrigger asChild>
                    <span className="inline-flex cursor-help">
                        {badge}
                    </span>
                </TooltipTrigger>
                <TooltipContent noArrow side="top" className="max-w-[320px] rounded-md bg-[#1D2129] px-3 py-2 text-left text-xs leading-5 text-white">
                    {statusReason}
                </TooltipContent>
            </Tooltip>
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

        if ((!isAdmin && !approvalStatusLabel) || isFolder) {
            return <span className={cn("truncate", nameToneClass)}>{file.name}</span>;
        }
        return (
            <div className="flex min-w-0 items-center gap-2">
                <span className={cn("min-w-0 flex-1 truncate", nameToneClass)}>{file.name}</span>
                {renderStatusBadge()}
            </div>
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
                "group rounded-md overflow-hidden border-[0.5px] p-0 gap-0 py-0 shadow-none touch-mobile:rounded-[6px]",
                cardOpensPreviewOrFolder ? "cursor-pointer" : "cursor-default",
                isSelected
                    ? "border-primary shadow-sm"
                    : "border-[#ECECEC] hover:border-[#c9cdd4]",
                hovered && "shadow-md"
            )}
            style={{
                transitionProperty: 'background-color',
                transitionDuration: '350ms',
                transitionTimingFunction: 'ease-in-out'
            }}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            onClick={handleCardClick}
        >
            <CardContent className={cn(
                "flex flex-col p-0",
                mobileListMode && "touch-mobile:flex-row touch-mobile:items-center touch-mobile:gap-2 touch-mobile:p-1"
            )}>
                {!hideSelectionCheckbox && mobileListMode && (
                    <div className="hidden touch-mobile:flex touch-mobile:shrink-0 touch-mobile:items-center touch-mobile:justify-center touch-mobile:pl-1 touch-mobile:pr-0.5">
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
                {/* 缩略图或图标区域 */}
                <div className={cn(
                    "relative flex h-[106px] shrink-0 items-center justify-center",
                    mobileListMode && "touch-mobile:h-12 touch-mobile:w-12 touch-mobile:rounded-[4px]",
                    isFolder ? "bg-[#FAFCFF]" : "bg-gray-50"
                )}>
                    <FileIconRenderer file={file} isFolder={isFolder} />

                    {!hideSelectionCheckbox && (
                        <div
                            className={cn(
                                "absolute left-2 top-2 z-10 transition-opacity",
                                mobileListMode && "touch-mobile:hidden",
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

                {/* 底部内容区域 */}
                <div className={cn(
                    "p-1",
                    mobileListMode && "touch-mobile:min-w-0 touch-mobile:flex-1 touch-mobile:pr-1"
                )}>
                    {/* 文件名和状态 */}
                    <div className="flex items-center text-sm font-medium min-w-0">
                        {getStatusText()}
                    </div>

                    {/* 底部信息 (标签、数量和时间) */}
                    <div className="flex items-center justify-between mt-1 min-w-0 gap-2">
                        <div className="flex items-center flex-1 min-w-0 min-h-[24px]">
                            {isAdmin && isFolder && file.fileNum != null && (
                                <span className="text-xs text-[#86909c] whitespace-nowrap">
                                    {localize("com_knowledge_items_count", { count: file.fileNum ?? 0 })}
                                </span>
                            )}
                            {!isAdmin && isFolder && file.fileNum != null && (
                                <span className="text-xs text-[#86909c] whitespace-nowrap">
                                    {localize("com_knowledge_items_count", { count: file.successFileNum ?? 0 })}
                                </span>
                            )}
                            {(!isFolder && file.tags && file.tags.length > 0) && (
                                <TagGroup tags={file.tags} />
                            )}
                        </div>
                        <span className="text-[#999] text-xs shrink-0 ">{formatTimeCard(file.updatedAt)}</span>
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
