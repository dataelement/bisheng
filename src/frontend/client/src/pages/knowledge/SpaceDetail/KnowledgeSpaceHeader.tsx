import {
    FolderPlus,
    ChevronLeft,
    Info,
    Download,
    Tag,
    RotateCcw,
    Trash2
} from "lucide-react";
import { Outlined } from "bisheng-icons";
import { KnowledgeSpace, FileStatus, SortType, SortDirection, SpaceRole, VisibilityType } from "~/api/knowledge";
import { cn } from "~/utils";
import { CompoundSearchInput, SearchParams } from "./CompoundSearchInput";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    DropdownMenuSeparator,
    DropdownMenuCheckboxItem
} from "~/components/ui/DropdownMenu";
import { knowledgeSpaceDropdownSurfaceClassName } from "~/components/SidebarListMoreMenu";
import { Button } from "~/components/ui/Button";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { CopyShareLinkButton } from "~/components/CopyShareLinkButton";
import { useLocalize, useMediaQuery, usePrefersMobileLayout } from "~/hooks";
import { Fragment } from "react";

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
    canCreateFolder?: boolean;
    canUploadFile?: boolean;
    /** Localized comma-joined list of supported upload formats for the upload-button tooltip. */
    supportedFormatsLabel?: string;

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
    onGoKnowledgeSquare?: () => void;
    enableCardMode?: boolean;
    canShareSpace?: boolean;
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
    canCreateFolder = false,
    canUploadFile = false,
    supportedFormatsLabel,
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
    onGoKnowledgeSquare,
    enableCardMode = true,
    canShareSpace = false,
}: KnowledgeSpaceHeaderProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const isNarrow576 = useMediaQuery("(max-width: 576px)");

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    const showShare = canShareSpace && space.visibility !== VisibilityType.PRIVATE;
    const selectedThreshold = isH5 ? 0 : 1;
    const showAddMenu = canCreateFolder || canUploadFile;
    const showViewModeTabs = enableCardMode && !isNarrow576;
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

    const viewFilterSortCluster = (
        <div className="flex min-w-0 shrink-0 items-center gap-3">
            {space.role !== SpaceRole.MEMBER && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button
                            variant="outline"
                            className={cn(
                                "inline-flex h-8 w-8 min-h-8 min-w-8 shrink-0 items-center justify-center gap-0 rounded-md p-0 font-normal border-[#e5e6eb]",
                                statusFilter.length > 0
                                    ? "border-[#024DE3] bg-[#E6EDFC] text-[#024DE3] hover:bg-[#E6EDFC]"
                                    : "bg-white text-[#818181] hover:bg-[#f7f8fa]"
                            )}
                        >
                            <Outlined.Filter className={cn("size-4", statusFilter.length > 0 ? "text-[#024DE3]" : "text-[#818181]")} />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className={knowledgeSpaceDropdownSurfaceClassName}>
                        <div className="px-2 py-1.5 text-xs font-medium text-[#86909c]">{localize("com_knowledge.status")}</div>
                        <DropdownMenuCheckboxItem
                            checked={statusFilter.includes(FileStatus.UPLOADING)}
                            onCheckedChange={(checked) => onFilterStatus(FileStatus.UPLOADING, checked)}
                            onSelect={(e) => e.preventDefault()}
                        >
                            {localize("com_knowledge.uploading_status")}
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem
                            checked={statusFilter.includes(FileStatus.WAITING)}
                            onCheckedChange={(checked) => onFilterStatus(FileStatus.WAITING, checked)}
                            onSelect={(e) => e.preventDefault()}
                        >
                            {localize("com_knowledge.queueing_status")}
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem
                            checked={statusFilter.includes(FileStatus.PROCESSING)}
                            onCheckedChange={(checked) => onFilterStatus(FileStatus.PROCESSING, checked)}
                            onSelect={(e) => e.preventDefault()}
                        >
                            {localize("com_knowledge.parsing_status")}
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem
                            checked={statusFilter.includes(FileStatus.REBUILDING)}
                            onCheckedChange={(checked) => onFilterStatus(FileStatus.REBUILDING, checked)}
                            onSelect={(e) => e.preventDefault()}
                        >
                            {localize("com_knowledge.rebuilding_status")}
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem
                            checked={statusFilter.includes(FileStatus.SUCCESS)}
                            onCheckedChange={(checked) => onFilterStatus(FileStatus.SUCCESS, checked)}
                            onSelect={(e) => e.preventDefault()}
                        >
                            {localize("com_knowledge.success")}
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem
                            checked={statusFilter.includes(FileStatus.FAILED)}
                            onCheckedChange={(checked) => onFilterStatus(FileStatus.FAILED, checked)}
                            onSelect={(e) => e.preventDefault()}
                        >
                            {localize("com_knowledge.fail")}
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem
                            checked={statusFilter.includes(FileStatus.VIOLATION)}
                            onCheckedChange={(checked) => onFilterStatus(FileStatus.VIOLATION, checked)}
                            onSelect={(e) => e.preventDefault()}
                        >
                            {localize("com_knowledge.violation")}
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem
                            checked={statusFilter.includes(FileStatus.TIMEOUT)}
                            onCheckedChange={(checked) => onFilterStatus(FileStatus.TIMEOUT, checked)}
                            onSelect={(e) => e.preventDefault()}
                        >
                            {localize("com_knowledge.timeout")}
                        </DropdownMenuCheckboxItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}

            {showViewModeTabs && viewMode === "card" && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button
                            variant="outline"
                            className="inline-flex h-8 w-8 min-h-8 min-w-8 shrink-0 items-center justify-center gap-0 rounded-md border border-[#e5e6eb] bg-white p-0 font-normal text-[#818181] hover:bg-[#f7f8fa]"
                        >
                            <Outlined.Sort className="size-4 shrink-0" aria-hidden />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className={knowledgeSpaceDropdownSurfaceClassName}>
                        <div className="px-2 py-1.5 text-xs font-medium text-[#86909c]">{localize("com_knowledge.sort_field")}</div>
                        <DropdownMenuItem onClick={() => onSort(SortType.NAME)}>
                            {localize("com_knowledge.sort_by_name_label")}
                            {sortBy === SortType.NAME && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => onSort(SortType.TYPE)}>
                            {localize("com_knowledge.sort_by_type_label")}
                            {sortBy === SortType.TYPE && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => onSort(SortType.UPDATE_TIME)}>
                            {localize("com_knowledge.sort_by_update_time_label")}
                            {sortBy === SortType.UPDATE_TIME && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    );

    const batchAndAddActions = showToolbarActions && (
        <div className="flex shrink-0 items-center gap-2">
            {selectedCount > selectedThreshold && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button size="sm" variant="outline" className="h-8 rounded-md border-[#e5e6eb] font-normal text-[#4e5969]">
                            {localize("com_knowledge.batch_operation")}
                            <Outlined.Down className="ml-1 size-4" />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className={knowledgeSpaceDropdownSurfaceClassName}>
                        {canBatchDownload && (
                            <DropdownMenuItem onClick={onBatchDownload} className="cursor-pointer">
                                <Download className="mr-2 size-4" />
                                {localize("com_knowledge.batch_download")}
                            </DropdownMenuItem>
                        )}
                        {isAdmin && !hasFoldersSelected && (
                            <DropdownMenuItem onClick={onBatchTag} className="cursor-pointer">
                                <Tag className="mr-2 size-4" />
                                {localize("com_knowledge.batch_add_tags")}
                            </DropdownMenuItem>
                        )}
                        {isAdmin && hasFailedFiles && (
                            <DropdownMenuItem onClick={onBatchRetry} className="cursor-pointer">
                                <RotateCcw className="mr-2 size-4" />
                                {localize("com_knowledge.batch_retry")}
                            </DropdownMenuItem>
                        )}
                        {canBatchDelete && (
                            <DropdownMenuItem onClick={onBatchDelete} className="cursor-pointer text-[#f53f3f] focus:text-[#f53f3f]">
                                <Trash2 className="mr-2 size-4" />
                                {localize("com_knowledge.batch_delete")}
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            {viewModeToggleButton}
            {showAddMenu && (
                canUploadFile ? (
                    // Split button per design 11495:14337: left half = direct upload, right half = dropdown
                    // (only "新建文件夹"). When canCreateFolder is false the chevron half is omitted and the
                    // shell becomes a single-action button.
                    <div className="inline-flex h-8 shrink-0 items-stretch overflow-hidden rounded-md border border-[#ebebeb] bg-white">
                        <button
                            type="button"
                            disabled={isSearching}
                            onClick={onTriggerUpload}
                            className={cn(
                                "inline-flex items-center justify-center px-4 text-sm text-[#212121] transition-colors",
                                "hover:bg-[#f7f8fa] disabled:cursor-not-allowed disabled:text-[#c9cdd4] disabled:hover:bg-transparent",
                                canCreateFolder && "border-r border-[#ebebeb]"
                            )}
                        >
                            {localize("com_knowledge.add_new")}
                        </button>
                        {canCreateFolder && (
                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <button
                                        type="button"
                                        disabled={isSearching}
                                        aria-label={localize("com_knowledge.add_new")}
                                        className="inline-flex items-center justify-center px-2 text-[#212121] transition-colors hover:bg-[#f7f8fa] disabled:cursor-not-allowed disabled:text-[#c9cdd4] disabled:hover:bg-transparent"
                                    >
                                        <Outlined.Down className="size-4" />
                                    </button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end" className={knowledgeSpaceDropdownSurfaceClassName}>
                                    <DropdownMenuItem onClick={onCreateFolder} className="cursor-pointer">
                                        <FolderPlus className="mr-2 size-4" />
                                        {localize("com_knowledge.new_folder")}
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                        )}
                    </div>
                ) : (
                    // Fallback when the user can only create folders: keep the original dropdown shape
                    // so the single available action is still discoverable.
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
                        <DropdownMenuContent align="end" className={knowledgeSpaceDropdownSurfaceClassName}>
                            <DropdownMenuItem onClick={onCreateFolder} className="cursor-pointer">
                                <FolderPlus className="mr-2 size-4" />
                                {localize("com_knowledge.new_folder")}
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )
            )}
        </div>
    );

    return (
        <div className="flex min-h-8 items-center justify-between gap-3 pt-5 pb-4 max-[767px]:gap-2 max-[767px]:pt-4 max-[767px]:pb-3">

                    {/* 左侧：当前空间标题 / 面包屑 + 信息 + 分享 */}
                    <div className="flex min-w-0 flex-1 items-center gap-1 text-sm">
                        {currentPath.length === 0 ? (
                            <div className="flex min-w-0 flex-1 items-center gap-1">
                                <h1 className="min-w-0 truncate text-base text-[#1d2129] max-[767px]:text-[16px] max-[767px]:leading-6">
                                    {space.name}
                                </h1>
                                {space.spaceKind === "department" && (
                                    <span className="inline-flex shrink-0 items-center rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-600">
                                        {localize("com_knowledge.department_badge")}
                                    </span>
                                )}
                                {/* {space.spaceKind === "department" && space.approvalEnabled !== undefined && ( */}
                                {space.spaceKind === "department" && space.approvalEnabled && (
                                    <span
                                        className={cn(
                                            "inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-[11px] font-medium",
                                            space.approvalEnabled
                                                ? "bg-[#E6EDFC] text-[#165DFF]"
                                                : "bg-[#F2F3F5] text-[#4E5969]",
                                        )}
                                    >
                                        {space.approvalEnabled
                                            ? localize("com_knowledge.approval_enabled_badge")
                                            : localize("com_knowledge.approval_disabled_badge")}
                                    </span>
                                )}
                                <Tooltip>
                                    <TooltipTrigger className="shrink-0 cursor-pointer">
                                        <Info className="size-4 text-[#86909c] outline-none hover:text-[#165dff]" />
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
                        ) : (
                            <>
                                {/* 移动端（<768px）：返回上一级 + 当前文件夹名 */}
                                <div className="flex min-w-0 items-center gap-2 text-[#1d2129] md:hidden">
                                    <button
                                        type="button"
                                        onClick={() => {
                                            const parent = currentPath[currentPath.length - 2];
                                            onNavigateFolder(parent?.id);
                                        }}
                                        aria-label={localize("com_ui_go_back")}
                                        className="inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-[#E5E6EB] bg-white text-[#4E5969] hover:bg-[#F7F8FA]"
                                    >
                                        <ChevronLeft className="size-4" />
                                    </button>
                                    <span className="min-w-0 truncate text-base font-medium text-[#1d2129] max-[767px]:text-[16px] max-[767px]:leading-6">
                                        {currentPath[currentPath.length - 1]?.name || space.name}
                                    </span>
                                </div>
                                {/* PC 端：完整文件路径（空间名 / 文件夹…） */}
                                <div className="hidden min-w-0 flex-1 items-center gap-0.5 overflow-x-auto text-sm text-[#1d2129] md:flex">
                                    <button
                                        type="button"
                                        onClick={() => onNavigateFolder(undefined)}
                                        className="max-w-[min(40%,12rem)] shrink-0 truncate text-left text-base text-[#1d2129] hover:text-[#165dff] hover:underline"
                                    >
                                        {space.name}
                                    </button>
                                    {currentPath.map((seg, idx) => (
                                        <Fragment key={seg.id ?? `path-${idx}`}>
                                            <span className="shrink-0 text-[#86909c]" aria-hidden>
                                                /
                                            </span>
                                            {idx === currentPath.length - 1 ? (
                                                <span className="min-w-0 truncate text-base font-medium text-[#1d2129]">
                                                    {seg.name}
                                                </span>
                                            ) : (
                                                <button
                                                    type="button"
                                                    onClick={() => onNavigateFolder(seg.id)}
                                                    className="max-w-[min(40%,12rem)] shrink-0 truncate text-left text-base text-[#1d2129] hover:text-[#165dff] hover:underline"
                                                >
                                                    {seg.name}
                                                </button>
                                            )}
                                        </Fragment>
                                    ))}
                                </div>
                            </>
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
