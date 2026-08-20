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
import { CopyShareLinkButton } from "~/components/CopyShareLinkButton";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";

/**
 * Space header: identity (name / info / share) on the left, batch + add actions
 * on the right. Search, filter, sort and the view toggle used to live here too;
 * they moved into FileListToolbar so list and card views share one bar
 * (Figma 13198:75829).
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
}: KnowledgeSpaceHeaderProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    const showShare = canShareSpace && space.visibility !== VisibilityType.PRIVATE;
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
                            className="inline-flex h-8 shrink-0 items-center justify-center gap-0.5 rounded-md border border-[#e5e6eb] bg-white px-3 text-sm font-normal text-text-2 transition-colors hover:bg-fill-1"
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
                            className="inline-flex h-8 shrink-0 items-center justify-center gap-1 rounded-md border border-[#ebebeb] bg-white px-4 text-sm text-[#212121] transition-colors hover:bg-[#f7f8fa] disabled:cursor-not-allowed disabled:text-[#c9cdd4] disabled:hover:bg-transparent"
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
                                                    knowledgeUploadCapabilities.media
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

            {/* 左侧：根目录显示空间标题 + 信息；进入文件夹后显示当前文件夹名（设计稿 11772:70584） */}
            <div className="flex min-w-0 flex-1 items-center gap-1 text-sm">
                {currentPath.length > 0 ? (
                    <>
                        {/* 返回按钮 + 分隔线先隐藏，后续可能恢复（设计稿 11772:70584）
                        <button
                            type="button"
                            onClick={() => {
                                const parent = currentPath[currentPath.length - 2];
                                onNavigateFolder(parent?.id);
                            }}
                            aria-label={localize("com_ui_go_back")}
                            className="inline-flex size-8 shrink-0 items-center justify-center rounded-md p-2 text-[#4e5969] transition-colors hover:bg-[#f7f8fa]"
                        >
                            <Outlined.ArrowLeft className="size-4" />
                        </button>
                        <div className="mx-1 h-4 w-px shrink-0 bg-[#e5e6eb]" aria-hidden />
                        */}
                        <h1 className="min-w-0 truncate text-base font-normal text-[#1d2129] max-[767px]:text-[16px] max-[767px]:leading-6">
                            {currentPath[currentPath.length - 1]?.name || space.name}
                        </h1>
                    </>
                ) : (
                    <div className="flex min-w-0 flex-1 items-center gap-1">
                        <h1 className="min-w-0 truncate text-base text-[#1d2129] max-[767px]:text-[16px] max-[767px]:leading-6">
                            {space.name}
                        </h1>
                        <Tooltip>
                            <TooltipTrigger className="shrink-0 cursor-pointer">
                                <Outlined.Info className="size-4 text-[#86909c] outline-none hover:text-blue-500" />
                            </TooltipTrigger>
                            <TooltipContent noArrow className="bg-white shadow-md px-3 py-2 max-w-md w-64 z-[999] relative">
                                <div className="space-y-1.5 text-gray-800 text-sm">
                                    <div><span className="text-gray-400">{localize("com_knowledge.space_desc_label")}</span>
                                        <p>{space.description || "-"}</p>
                                    </div>
                                    <div><span className="text-gray-400">{localize("com_knowledge.creator_label")}</span>
                                        <p>{space.creator}</p>
                                    </div>
                                    <div><span className="text-gray-400">{localize("com_knowledge.joined_count_label")}</span>
                                        <p>{space.memberCount || 0}</p>
                                    </div>
                                    <div><span className="text-gray-400">{localize("com_knowledge.total_files_label")}</span>
                                        <p>{space.totalFileCount || 0}</p>
                                    </div>
                                </div>
                            </TooltipContent>
                        </Tooltip>
                    </div>
                )}
            </div>

            {/* 右侧：分享 + 批量操作 + 新增。搜索/筛选/排序/视图切换已移入 FileListToolbar */}
            <div className="flex shrink-0 items-center gap-3">
                {showShare && (
                    <CopyShareLinkButton
                        iconOnly
                        variant="outline"
                        sharePath={`/knowledge/share/${space.id}`}
                        successMessage={localize("com_knowledge.share_link_copied")}
                        errorMessage={localize("com_knowledge.copy_failed_retry")}
                        className="size-8 shrink-0 rounded-md border border-[#ebebeb] bg-white p-0 transition-colors hover:bg-[#f7f8fa]"
                        icon={<Outlined.Share className="size-4 text-[#4e5969]" />}
                        aria-label={localize("com_knowledge.share")}
                    />
                )}
                {batchAndAddActions}
            </div>
        </div>
    );
}
