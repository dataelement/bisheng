import { CircleHelp, FolderPlus, FolderUp, Link2 } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { KnowledgeSpace, FileStatus, SortType, SortDirection, SpaceRole, VisibilityType } from "~/api/knowledge";
import { cn } from "~/utils";
import { CompoundSearchInput, SearchParams } from "./CompoundSearchInput";
import {
    DropdownMenu,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import {
    ActionMenuCheckboxItem,
    ActionMenuContent,
    ActionMenuItem,
    actionMenuLabelClassName,
    actionMenuSectionLabelClassName,
} from "~/components/ActionMenu";
import { Button } from "~/components/ui/Button";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { CopyShareLinkButton } from "~/components/CopyShareLinkButton";
import { useLocalize, useMediaQuery, usePrefersMobileLayout } from "~/hooks";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";

/** Status options, in the order the filter menu lists them. */
const STATUS_FILTER_OPTIONS: Array<{ value: FileStatus; labelKey: string }> = [
    { value: FileStatus.UPLOADING, labelKey: "com_knowledge.uploading_status" },
    { value: FileStatus.WAITING, labelKey: "com_knowledge.queueing_status" },
    { value: FileStatus.PROCESSING, labelKey: "com_knowledge.parsing_status" },
    { value: FileStatus.REBUILDING, labelKey: "com_knowledge.rebuilding_status" },
    { value: FileStatus.SUCCESS, labelKey: "com_knowledge.success" },
    { value: FileStatus.FAILED, labelKey: "com_knowledge.fail" },
    { value: FileStatus.VIOLATION, labelKey: "com_knowledge.violation" },
    { value: FileStatus.TIMEOUT, labelKey: "com_knowledge.timeout" },
];

const SORT_OPTIONS: Array<{ value: SortType; labelKey: string }> = [
    { value: SortType.NAME, labelKey: "com_knowledge.sort_by_name_label" },
    { value: SortType.TYPE, labelKey: "com_knowledge.sort_by_type_label" },
    { value: SortType.UPDATE_TIME, labelKey: "com_knowledge.sort_by_update_time_label" },
];

interface KnowledgeSpaceHeaderProps {
    space: KnowledgeSpace;
    currentPath: Array<{ id?: string; name: string }>;
    onNavigateFolder: (folderId?: string) => void;
    searchQuery: string;
    isSearching: boolean;
    onSearch: (params: SearchParams) => void;
    viewMode: "card" | "list";
    setViewMode: (mode: "card" | "list") => void;
    statusFilter: FileStatus[];
    onFilterStatus: (status: FileStatus, checked: boolean) => void;
    sortBy: SortType | undefined;
    sortDirection: SortDirection | undefined;
    onSort: (sortBy: SortType) => void;
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
    enableCardMode?: boolean;
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
    searchQuery,
    isSearching,
    onSearch,
    viewMode,
    setViewMode,
    statusFilter,
    onFilterStatus,
    sortBy,
    sortDirection,
    onSort,
    onCreateFolder,
    onTriggerUpload,
    onTriggerUploadFolder,
    onTriggerWebLink,
    canCreateFolder = false,
    canUploadFile = false,
    selectedCount,
    hasFoldersSelected,
    hasFailedFiles,
    onClearSelection,
    onBatchDownload,
    canBatchDownload = false,
    onBatchTag,
    onBatchRetry,
    onBatchDelete,
    canBatchDelete = false,
    onBatchMove,
    canBatchMove = false,
    onGoKnowledgeSquare,
    enableCardMode = true,
    canShareSpace = false,
    versionManagementEnabled = false,
    hasSimilarSelected = false,
    onProcessSimilar,
    canManageMembers = false,
}: KnowledgeSpaceHeaderProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const isNarrow576 = useMediaQuery("(max-width: 576px)");

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    const showShare = canShareSpace && space.visibility !== VisibilityType.PRIVATE;
    const selectedThreshold = isH5 ? 0 : 1;
    const showAddMenu = canCreateFolder || canUploadFile;
    const showViewModeTabs = enableCardMode && !isNarrow576;
    const showFilterButton = space.role !== SpaceRole.MEMBER;
    const showSortButton = showViewModeTabs && viewMode === "card";
    const showFilterSortCluster = showFilterButton || showSortButton;
    // Include the view-mode toggle here so the trailing button group still renders for
    // viewers (no add menu, not admin, no selection) who only have the toggle to show.
    const showToolbarActions = showAddMenu || isAdmin || selectedCount > selectedThreshold || showViewModeTabs;

    const viewModeToggleButton = showViewModeTabs ? (
        <Button
            variant="outline"
            onClick={() => setViewMode(viewMode === "list" ? "card" : "list")}
            className="inline-flex h-8 w-8 min-h-8 min-w-8 shrink-0 items-center justify-center gap-0 rounded-md border border-[#e5e6eb] bg-white p-0 font-normal text-[#818181] hover:bg-[#f7f8fa]"
        >
            {viewMode === "list"
                ? <Outlined.ViewGridCard className="size-4 shrink-0" />
                : <Outlined.List className="size-4 shrink-0" />}
        </Button>
    ) : null;

    const viewFilterSortCluster = showFilterSortCluster && (
        <div className="flex min-w-0 shrink-0 items-center gap-3">
            {showFilterButton && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button
                            variant="outline"
                            className={cn(
                                "inline-flex h-8 w-8 min-h-8 min-w-8 shrink-0 items-center justify-center gap-0 rounded-md p-0 font-normal border-[#e5e6eb]",
                                statusFilter.length > 0
                                    ? "border-blue-600 bg-blue-500/[0.07] text-blue-600 hover:bg-blue-500/[0.07]"
                                    : "bg-white text-[#818181] hover:bg-[#f7f8fa]"
                            )}
                        >
                            <Outlined.Filter className={cn("size-4", statusFilter.length > 0 ? "text-blue-600" : "text-[#818181]")} />
                        </Button>
                    </DropdownMenuTrigger>
                    {/* 120px panel centred on the trigger, 8px padding, 32px rows
                        spaced 4px apart, 12px radius; scrolls past 240px. */}
                    <ActionMenuContent
                        align="center"
                        width={120}
                        className="max-h-[240px] min-w-0 gap-1 overflow-y-auto rounded-xl"
                    >
                        <div className={actionMenuSectionLabelClassName}>{localize("com_knowledge.status")}</div>
                        {STATUS_FILTER_OPTIONS.map((option) => (
                            <ActionMenuCheckboxItem
                                key={option.value}
                                checked={statusFilter.includes(option.value)}
                                onCheckedChange={(checked) => onFilterStatus(option.value, checked)}
                                onSelect={(e) => e.preventDefault()}
                            >
                                <span className={actionMenuLabelClassName}>{localize(option.labelKey)}</span>
                            </ActionMenuCheckboxItem>
                        ))}
                    </ActionMenuContent>
                </DropdownMenu>
            )}

            {showSortButton && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button
                            variant="outline"
                            className="inline-flex h-8 w-8 min-h-8 min-w-8 shrink-0 items-center justify-center gap-0 rounded-md border border-[#e5e6eb] bg-white p-0 font-normal text-[#818181] hover:bg-[#f7f8fa]"
                        >
                            <Outlined.Sort className="size-4 shrink-0" aria-hidden />
                        </Button>
                    </DropdownMenuTrigger>
                    {/* Same panel as the filter menu; the active field's direction sits
                        in the trailing slot the filter uses for its check. */}
                    <ActionMenuContent
                        align="center"
                        width={120}
                        className="max-h-[240px] min-w-0 gap-1 overflow-y-auto rounded-xl"
                    >
                        <div className={actionMenuSectionLabelClassName}>{localize("com_knowledge.sort_field")}</div>
                        {SORT_OPTIONS.map((option) => (
                            <ActionMenuItem
                                key={option.value}
                                className="rounded-lg"
                                onClick={() => onSort(option.value)}
                            >
                                <span className={actionMenuLabelClassName}>{localize(option.labelKey)}</span>
                                {sortBy === option.value && (
                                    <span className="ml-auto flex size-4 shrink-0 items-center justify-center text-primary">
                                        {sortDirection === SortDirection.ASC
                                            ? <Outlined.ArrowUp className="size-4" />
                                            : <Outlined.ArrowDown className="size-4" />}
                                    </span>
                                )}
                            </ActionMenuItem>
                        ))}
                    </ActionMenuContent>
                </DropdownMenu>
            )}
        </div>
    );

    const batchAndAddActions = showToolbarActions && (
        <div className="flex shrink-0 items-center gap-2">
            {viewModeToggleButton}
            {selectedCount > selectedThreshold && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button size="sm" variant="outline" className="h-8 gap-0.5 rounded-md border-[#e5e6eb] font-normal text-[#4e5969]">
                            {localize("com_knowledge.batch_operation")}
                            <Outlined.Down className="size-4" />
                        </Button>
                    </DropdownMenuTrigger>
                    <ActionMenuContent align="end">
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
                    <ActionMenuContent align="end" width={200}>
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
        <div className="flex min-h-8 items-center justify-between gap-3 pt-4 pb-4 max-[767px]:gap-2 max-[767px]:pb-3">

                    {/* 左侧：根目录显示空间标题 + 信息 + 分享；进入文件夹后显示返回按钮 + 分隔线 + 当前文件夹名（设计稿 11772:70584） */}
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
                                {showShare && (
                                    <CopyShareLinkButton
                                        iconOnly
                                        sharePath={`/knowledge/share/${space.id}`}
                                        successMessage={localize("com_knowledge.share_link_copied")}
                                        errorMessage={localize("com_knowledge.copy_failed_retry")}
                                        className="ml-1 size-7 border-0"
                                        icon={<Outlined.Share className="size-4 text-[#4e5969]" />}
                                        aria-label={localize("com_knowledge.share")}
                                    />
                                )}
                            </div>
                        )}
                    </div>

                    {/* 右侧：搜索（收起为图标，点击展开）+ 视图/筛选/排序 + 批量/新增，单行排列 */}
                    <div className="flex shrink-0 items-center gap-3">
                        <CompoundSearchInput
                            collapsible
                            spaceId={space.id}
                            isRoot={currentPath.length === 0}
                            onSearch={onSearch}
                        />
                        {viewFilterSortCluster}
                        {batchAndAddActions}
                    </div>
        </div>
    );
}
