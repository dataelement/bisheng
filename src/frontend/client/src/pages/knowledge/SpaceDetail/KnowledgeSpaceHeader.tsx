import { useLocation, useNavigate } from "react-router-dom";
import { knowledgePathWithTab } from "../knowledgeListNavigation";
import { CircleHelp, FolderPlus, FolderUp, Link2 } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { KnowledgeSpace, SpaceRole, VisibilityType } from "~/api/knowledge";
import {
    DropdownMenu,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import {
    ActionMenuContent,
    ActionMenuItem,
    actionMenuLabelClassName,
} from "~/components/ActionMenu";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { SpaceBreadcrumb } from "./SpaceBreadcrumb";
import { SpaceActionMenuItems, getSpaceActionFlags } from "./SpaceActionMenuItems";
import { CopyShareLinkButton } from "~/components/CopyShareLinkButton";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";
import { useRecoilValue } from "recoil";
import { bishengConfState } from "~/pages/appChat/store/atoms";

/**
 * Space header: location trail (space anchor + folder path, with the space action
 * menu hanging off the first segment) on the left, share / batch / add actions on
 * the right. Search, filter, sort and the view toggle used to live here too; they
 * moved into FileListToolbar so list and card views share one bar (Figma 13198:75829).
 */
interface KnowledgeSpaceHeaderProps {
    space: KnowledgeSpace;
    currentPath: Array<{ id?: string; name: string }>;
    onNavigateFolder: (folderId?: string) => void;
    isSearching: boolean;
    onCreateFolder: () => void;
    onTriggerUpload: () => void;
    onTriggerUploadFolder: () => void;
    onTriggerWebLink: () => void;
    canCreateFolder?: boolean;
    canUploadFile?: boolean;

    // Batch Operation Props
    selectedCount: number;
    hasFoldersSelected: boolean;
    hasFailedFiles: boolean;
    onClearSelection: () => void;
    onBatchDownload: () => void;
    canBatchDownload?: boolean;
    onBatchTag: () => void;
    onBatchRetry: () => void;
    onBatchDelete: () => void;
    canBatchDelete?: boolean;
    /** F034: batch-move selected files/folders. Shown when provided. */
    onBatchMove?: () => void;
    /** F034: whether the current selection can be moved (no uploading placeholders + move permission). */
    canBatchMove?: boolean;
    onGoKnowledgeSquare?: () => void;
    canShareSpace?: boolean;
    /** Version management: gates the "process similar documents" entry + per-row version actions. */
    versionManagementEnabled?: boolean;
    /** True when the current selection contains at least one pending similar document. */
    hasSimilarSelected?: boolean;
    /** Opens the similar-document processing dialog (restricted to the current selection). */
    onProcessSimilar?: () => void;
    /** Whether the current user can manage members (gates the process-similar entry). */
    canManageMembers?: boolean;

    // ── Space-level actions (breadcrumb menu; available at every folder depth) ──
    /** Opens the space settings page/drawer. */
    onOpenSettings?: () => void;
    /** Deletes the space (owns its own confirm) and returns to the space list. */
    onDeleteSpace?: () => void;
    /** Leaves a joined space (owns its own confirm). */
    onLeaveSpace?: () => void;
    canEditSpace?: boolean;
    canDeleteSpace?: boolean;
    canLeaveSpace?: boolean;
}

export function KnowledgeSpaceHeader({
    space,
    currentPath,
    onNavigateFolder,
    isSearching,
    onCreateFolder,
    onTriggerUpload,
    onTriggerUploadFolder,
    onTriggerWebLink,
    canCreateFolder = false,
    canUploadFile = false,
    selectedCount,
    hasFoldersSelected,
    hasFailedFiles,
    onBatchDownload,
    canBatchDownload = false,
    onBatchTag,
    onBatchRetry,
    onBatchDelete,
    canBatchDelete = false,
    onBatchMove,
    canBatchMove = false,
    canShareSpace = false,
    versionManagementEnabled = false,
    hasSimilarSelected = false,
    onProcessSimilar,
    canManageMembers = false,
    onOpenSettings,
    onDeleteSpace,
    onLeaveSpace,
    canEditSpace = false,
    canDeleteSpace = false,
    canLeaveSpace = false,
}: KnowledgeSpaceHeaderProps) {
    const localize = useLocalize();
    const navigate = useNavigate();
    const location = useLocation();
    const bishengConfig = useRecoilValue(bishengConfState);
    const isH5 = usePrefersMobileLayout();

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    const showShare = canShareSpace && space.visibility !== VisibilityType.PRIVATE;
    const spaceActions = {
        space,
        onOpenSettings,
        onDeleteSpace,
        onLeaveSpace,
        canEditSpace,
        canManageMembers,
        canDeleteSpace,
        canLeaveSpace,
    };
    // Root only: deeper in, the same actions hang off the breadcrumb's space
    // segment, and a second copy up here would read as the current folder's.
    // Also hidden when every row is permission-gated away — an empty menu.
    const showSpaceSettingsButton =
        currentPath.length === 0 && getSpaceActionFlags(spaceActions).hasAny;
    const selectedThreshold = isH5 ? 0 : 1;
    const showAddMenu = canCreateFolder || canUploadFile;
    // Filter / sort / search / view-toggle all moved into FileListToolbar.
    const showToolbarActions = showAddMenu || isAdmin || selectedCount > selectedThreshold;

    const batchAndAddActions = showToolbarActions && (
        <div className="flex shrink-0 items-center gap-2">
            {selectedCount > selectedThreshold && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <button
                            type="button"
                            className="inline-flex h-8 shrink-0 items-center justify-center gap-0.5 rounded-md border border-border-base bg-white px-3 text-sm font-normal text-text-2 transition-colors hover:bg-fill-1"
                        >
                            {localize("com_knowledge.batch_operation")}
                            <Outlined.Down className="size-4" />
                        </button>
                    </DropdownMenuTrigger>
                    <ActionMenuContent align="end" width={140}>
                        {versionManagementEnabled && canManageMembers && hasSimilarSelected && onProcessSimilar && (
                            <ActionMenuItem
                                onClick={onProcessSimilar}
                                icon={<Outlined.FileSearch />}
                                label={localize("com_knowledge.version.header_process_similar_label")}
                            />
                        )}
                        {canBatchDownload && (
                            <ActionMenuItem
                                onClick={onBatchDownload}
                                icon={<Outlined.Download />}
                                label={localize("com_knowledge.batch_download")}
                            />
                        )}
                        {isAdmin && !hasFoldersSelected && (
                            <ActionMenuItem
                                onClick={onBatchTag}
                                icon={<Outlined.Tag />}
                                label={localize("com_knowledge.batch_add_tags")}
                            />
                        )}
                        {isAdmin && hasFailedFiles && (
                            <ActionMenuItem
                                onClick={onBatchRetry}
                                icon={<Outlined.Refresh />}
                                label={localize("com_knowledge.batch_retry")}
                            />
                        )}
                        {onBatchMove && (
                            <ActionMenuItem
                                disabled={!canBatchMove}
                                onClick={onBatchMove}
                                icon={<Outlined.MoveToFolder />}
                                label={localize("com_knowledge.move")}
                            />
                        )}
                        {canBatchDelete && (
                            <ActionMenuItem
                                danger
                                onClick={onBatchDelete}
                                icon={<Outlined.Delete />}
                                label={localize("com_knowledge.batch_delete")}
                            />
                        )}
                    </ActionMenuContent>
                </DropdownMenu>
            )}
            {showAddMenu && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <button
                            type="button"
                            disabled={isSearching}
                            className="inline-flex h-8 shrink-0 items-center justify-center gap-1 rounded-md border border-border-base bg-white px-4 text-sm text-text-1 transition-colors hover:bg-fill-1 disabled:cursor-not-allowed disabled:text-text-4 disabled:hover:bg-transparent"
                        >
                            {localize("com_knowledge.add_new")}
                            <Outlined.Down className="size-4" />
                        </button>
                    </DropdownMenuTrigger>
                    <ActionMenuContent align="end">
                        {canCreateFolder && (
                            <ActionMenuItem
                                onClick={onCreateFolder}
                                icon={<FolderPlus />}
                                label={localize("com_knowledge.new_folder")}
                            />
                        )}
                        {canUploadFile && (
                            <>
                                <ActionMenuItem
                                    onClick={onTriggerUpload}
                                    icon={<Outlined.Upload />}
                                >
                                    <div className="flex min-w-0 flex-1 items-center">
                                        <span className={actionMenuLabelClassName}>
                                            {localize("com_knowledge.upload_file")}
                                        </span>
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <span
                                                    className="ml-auto inline-flex size-4 shrink-0 items-center justify-center text-[#8a94a6]"
                                                    onClick={(event) => event.stopPropagation()}
                                                    onPointerDown={(event) => event.stopPropagation()}
                                                >
                                                    <CircleHelp className="size-3.5" />
                                                </span>
                                            </TooltipTrigger>
                                            <TooltipContent
                                                side="top"
                                                className="z-[999] max-w-md"
                                            >
                                                {localize(
                                                    bishengConfig?.enable_media_upload
                                                        ? "com_knowledge.upload_file_types_tip"
                                                        : "com_knowledge.upload_file_types_tip_without_media",
                                                )}
                                            </TooltipContent>
                                        </Tooltip>
                                    </div>
                                </ActionMenuItem>
                                <ActionMenuItem
                                    onClick={onTriggerUploadFolder}
                                    icon={<FolderUp />}
                                    label={localize("com_knowledge.upload_folder")}
                                />
                                {knowledgeUploadCapabilities.webLink && (
                                    <ActionMenuItem
                                        onClick={onTriggerWebLink}
                                        icon={<Link2 />}
                                        label={localize("com_knowledge.web_link")}
                                    />
                                )}
                            </>
                        )}
                    </ActionMenuContent>
                </DropdownMenu>
            )}
        </div>
    );

    return (
        <div className="flex min-h-8 items-center justify-between gap-3 px-4 pb-4 pt-4 max-[767px]:gap-2 max-[767px]:pb-3">

            {/* 左侧：返回 + 位置面包屑。首段永远是空间本身，空间级操作挂在它的下拉里，
                所以下钻到任意层级都不会丢失「我在哪个空间」和空间级操作（设计稿 11772:70584） */}
            {/* -ml-2 pulls the whole group 8px left on its own, without touching the
                row's px-4 — that padding is shared with the right-hand actions, so
                shrinking it there would drag those 8px right along with it. */}
            <div className="-ml-2 flex min-w-0 flex-1 items-center gap-1 text-sm">
                {/* Desktop back button. The module has no space / folder column any more,
                    so this is the way up: folder → parent folder → space root → the
                    知识空间 home. Mobile keeps its own top bar and Title ▾ drawer. */}
                <button
                    type="button"
                    onClick={() => {
                        if (currentPath.length === 0) {
                            navigate(knowledgePathWithTab("/knowledge", location.search));
                            return;
                        }
                        const parent = currentPath[currentPath.length - 2];
                        onNavigateFolder(parent?.id);
                    }}
                    aria-label={localize("com_ui_go_back")}
                    className="inline-flex size-8 shrink-0 items-center justify-center rounded-md p-2 text-text-2 transition-colors hover:bg-fill-1 max-[767px]:hidden"
                >
                    <Outlined.ArrowLeft className="size-4" />
                </button>
                <div className="mx-1 h-4 w-px shrink-0 bg-border-base max-[767px]:hidden" aria-hidden />
                <SpaceBreadcrumb
                    space={space}
                    currentPath={currentPath}
                    onNavigateFolder={onNavigateFolder}
                    onOpenSettings={onOpenSettings}
                    onDeleteSpace={onDeleteSpace}
                    onLeaveSpace={onLeaveSpace}
                    canEditSpace={canEditSpace}
                    canManageMembers={canManageMembers}
                    canDeleteSpace={canDeleteSpace}
                    canLeaveSpace={canLeaveSpace}
                />
            </div>

            {/* 右侧：分享 + 设置 + 批量操作 + 新增。搜索/筛选/排序/视图切换已移入 FileListToolbar */}
            <div className="flex shrink-0 items-center gap-3">
                {showShare && (
                    <CopyShareLinkButton
                        iconOnly
                        variant="outline"
                        sharePath={`/knowledge/share/${space.id}`}
                        successMessage={localize("com_knowledge.share_link_copied")}
                        errorMessage={localize("com_knowledge.copy_failed_retry")}
                        className="size-8 shrink-0 rounded-md border border-[#ebebeb] bg-white p-0 transition-colors hover:bg-fill-1"
                        icon={<Outlined.Share className="size-4 text-text-2" />}
                        aria-label={localize("com_knowledge.share")}
                    />
                )}
                {showSpaceSettingsButton && (
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button
                                type="button"
                                aria-label={localize("com_knowledge.space_settings")}
                                className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-border-base bg-white text-text-2 transition-colors hover:bg-fill-1 data-[state=open]:bg-fill-1"
                            >
                                <Outlined.MoreCircle className="size-4" />
                            </button>
                        </DropdownMenuTrigger>
                        <ActionMenuContent align="end" width={180}>
                            <SpaceActionMenuItems {...spaceActions} />
                        </ActionMenuContent>
                    </DropdownMenu>
                )}
                {batchAndAddActions}
            </div>
        </div>
    );
}
