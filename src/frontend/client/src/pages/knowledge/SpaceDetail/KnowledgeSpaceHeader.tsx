import {
    LayoutGrid,
    List,
    Upload,
    FolderPlus,
    ChevronDown,
    ChevronRight,
    Info,
    FunnelIcon,
    Download,
    Tag,
    RotateCcw,
    Trash2
} from "lucide-react";
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
import { AiChatIcon } from "~/components/icons";
import { CopyShareLinkButton } from "~/components/CopyShareLinkButton";
import { SingleIconButtonSortGlyph } from "~/components/icons/channels";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useLayoutEffect, useRef, useState, useEffect } from "react";
import { ChannelBlocksArrowsIcon } from "~/components/icons/channels";

/** 工具栏实际宽度小于此值时：搜索独占一行，第二行为视图/筛选（左）与新增/批量（右）。阈值偏大以免中等宽度仍挤在一行。 */
const TOOLBAR_COMPACT_MAX_WIDTH = 1040;

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

    // Batch Operation Props
    selectedCount: number;
    hasFoldersSelected: boolean;
    hasFailedFiles: boolean;
    onClearSelection: () => void;
    onBatchDownload: () => void;
    onBatchTag: () => void;
    onBatchRetry: () => void;
    onBatchDelete: () => void;
    onGoKnowledgeSquare?: () => void;
    onToggleAiAssistant?: () => void;
    isAiAssistantOpen?: boolean;
    enableCardMode?: boolean;
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
    selectedCount,
    hasFoldersSelected,
    hasFailedFiles,
    onClearSelection,
    onBatchDownload,
    onBatchTag,
    onBatchRetry,
    onBatchDelete,
    onGoKnowledgeSquare,
    onToggleAiAssistant,
    isAiAssistantOpen,
    enableCardMode = true,
}: KnowledgeSpaceHeaderProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const toolbarMeasureRef = useRef<HTMLDivElement>(null);
    const [toolbarCompact, setToolbarCompact] = useState(false);

    useLayoutEffect(() => {
        const el = toolbarMeasureRef.current;
        if (!el) return;
        const update = () => {
            const w = el.getBoundingClientRect().width;
            setToolbarCompact(w > 0 && w < TOOLBAR_COMPACT_MAX_WIDTH);
        };
        update();
        const ro = new ResizeObserver(() => update());
        ro.observe(el);
        return () => ro.disconnect();
    }, []);

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    const showShare = space.visibility !== VisibilityType.PRIVATE;
    const selectedThreshold = isH5 ? 0 : 1;
    const showToolbarActions = isAdmin || selectedCount > selectedThreshold;

    const viewFilterSortCluster = (
        <div className="flex min-w-0 shrink-0 items-center gap-3">
            <div className="inline-flex h-8 shrink-0 items-stretch rounded-md border border-[#e5e6eb] bg-white p-[3px] text-sm">
                <button
                    type="button"
                    onClick={() => setViewMode("list")}
                    className={cn(
                        "flex min-w-[36px] flex-1 items-center justify-center rounded-[4px] px-2 transition-colors",
                        viewMode === "list"
                            ? "bg-[#E6EDFC] text-[#165DFF]"
                            : "text-[#4e5969] hover:bg-[#f2f3f5]"
                    )}
                >
                    <List className="size-4 shrink-0" />
                </button>
                {enableCardMode && (
                    <button
                        type="button"
                        onClick={() => setViewMode("card")}
                        className={cn(
                            "flex min-w-[36px] flex-1 items-center justify-center rounded-[4px] px-2 transition-colors",
                            viewMode === "card"
                                ? "bg-[#E6EDFC] text-[#165DFF]"
                                : "text-[#4e5969] hover:bg-[#f2f3f5]"
                        )}
                    >
                        <LayoutGrid className="size-4 shrink-0" />
                    </button>
                )}
            </div>

            {space.role !== SpaceRole.MEMBER && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button
                            variant="outline"
                            className={cn(
                                "inline-flex h-8 w-8 min-h-8 min-w-8 shrink-0 items-center justify-center gap-0 rounded-md p-0 font-normal border-[#e5e6eb]",
                                statusFilter.length > 0
                                    ? "border-[#024DE3] bg-[#E6EDFC] text-[#024DE3] hover:bg-[#E6EDFC]"
                                    : "bg-white text-gray-700 hover:bg-[#f7f8fa]"
                            )}
                        >
                            <FunnelIcon className={cn("size-4", statusFilter.length > 0 ? "text-[#024DE3]" : "text-gray-700")} />
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
                            checked={statusFilter.includes(FileStatus.TIMEOUT)}
                            onCheckedChange={(checked) => onFilterStatus(FileStatus.TIMEOUT, checked)}
                            onSelect={(e) => e.preventDefault()}
                        >
                            {localize("com_knowledge.timeout")}
                        </DropdownMenuCheckboxItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}

            {enableCardMode && viewMode === "card" && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button
                            variant="outline"
                            className="inline-flex h-8 w-8 min-h-8 min-w-8 shrink-0 items-center justify-center gap-0 rounded-md border border-[#e5e6eb] bg-white p-0 font-normal text-gray-700"
                        >
                            <SingleIconButtonSortGlyph className="size-4 shrink-0" aria-hidden />
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
                            <ChevronDown className="ml-1 size-4" />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className={knowledgeSpaceDropdownSurfaceClassName}>
                        <DropdownMenuItem onClick={onBatchDownload} className="cursor-pointer">
                            <Download className="mr-2 size-4" />
                            {localize("com_knowledge.batch_download")}
                        </DropdownMenuItem>
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
                        {isAdmin && (
                            <DropdownMenuItem onClick={onBatchDelete} className="cursor-pointer text-[#f53f3f] focus:text-[#f53f3f]">
                                <Trash2 className="mr-2 size-4" />
                                {localize("com_knowledge.batch_delete")}
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            {isAdmin && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button size="sm" className="h-8 rounded-md px-4 font-normal" disabled={isSearching}>
                            {localize("com_knowledge.add_new")}
                            <ChevronDown className="ml-1 size-4" />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className={knowledgeSpaceDropdownSurfaceClassName}>
                        <DropdownMenuItem onClick={onCreateFolder} className="cursor-pointer">
                            <FolderPlus className="mr-2 size-4" />
                            {localize("com_knowledge.new_folder")}
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={onTriggerUpload} className="cursor-pointer">
                            <Upload className="mr-2 size-4" />
                            {localize("com_knowledge.upload_file")}
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    );

    const searchFieldClassName = toolbarCompact
        ? "relative min-w-0 w-full"
        : cn(
            "relative min-w-0 w-full transition-[width,max-width,flex-grow] duration-200 ease-out",
            "sm:flex-none sm:w-[450px] sm:max-w-[450px] sm:shrink-0",
            // Driven by CompoundSearchInput's data-expanded attribute (input focus
            // OR scope DropdownMenu open) — survives Radix portal moving focus
            // outside the search field.
            "sm:has-[[data-expanded=true]]:flex-1 sm:has-[[data-expanded=true]]:w-auto sm:has-[[data-expanded=true]]:max-w-none sm:has-[[data-expanded=true]]:min-w-0"
        );

    return (
        <>
        <div className="space-y-4 pt-5 pb-4 touch-mobile:space-y-3 touch-mobile:pt-4 touch-mobile:pb-3">
            {currentPath.length === 0 ? (
                <div className="hidden touch-mobile:flex items-end gap-3">
                    <h1 className="text-[24px] font-semibold leading-8 text-[#335CFF]">
                        {localize("com_knowledge.knowledge_space")}
                    </h1>
                    {onGoKnowledgeSquare ? (
                        <button
                            type="button"
                            onClick={onGoKnowledgeSquare}
                            className="inline-flex items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-[#212121] hover:bg-[#F7F8FA]"
                        >
                            <ChannelBlocksArrowsIcon className="size-4 text-[#86909C]" />
                            <span className="text-[12px] leading-5 font-normal text-[#212121]">
                                前往知识广场
                            </span>
                        </button>
                    ) : null}
                </div>
            ) : null}

            {/* 面包屑 / 当前空间标题 */}
            <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-center gap-1 text-sm">
                    {currentPath.length === 0 ? (
                        <div className="flex items-center gap-1">
                            <h1 className="text-base text-[#1d2129] touch-mobile:text-[16px] touch-mobile:leading-6">{space.name}</h1>
                            {space.spaceKind === "department" && (
                                <span className="inline-flex items-center rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-600">
                                    {localize("com_knowledge.department_badge")}
                                </span>
                            )}
                            <Tooltip>
                                <TooltipTrigger className="cursor-pointer">
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
                        </div>
                    ) : (
                        <div className="flex items-center gap-1 text-[#1d2129]">
                            <button
                                onClick={() => onNavigateFolder(undefined)}
                                className="text-[#4e5969] hover:text-[#165dff] shrink-0"
                            >
                                {space.name}
                            </button>
                            {(() => {
                                // Show ellipsis when path is longer than 3 levels
                                const MAX_VISIBLE = 3;
                                let visibleItems = currentPath;
                                let showEllipsis = false;
                                if (currentPath.length > MAX_VISIBLE) {
                                    // Show first item, ellipsis, then last 2 items
                                    visibleItems = [
                                        currentPath[0],
                                        ...currentPath.slice(-2),
                                    ];
                                    showEllipsis = true;
                                }
                                return visibleItems.map((item, displayIdx) => {
                                    const isLast = displayIdx === visibleItems.length - 1;
                                    return (
                                        <div key={item.id} className="flex items-center gap-1 min-w-0">
                                            <span className="text-[#86909c] mx-0.5 shrink-0">/</span>
                                            {showEllipsis && displayIdx === 1 && (
                                                <>
                                                    <span className="text-[#86909c]">...</span>
                                                    <span className="text-[#86909c] mx-0.5 shrink-0">/</span>
                                                </>
                                            )}
                                            {isLast ? (
                                                <span className="font-medium text-[#1d2129] truncate max-w-[160px]">
                                                    {item.name}
                                                </span>
                                            ) : (
                                                <button
                                                    onClick={() => onNavigateFolder(item.id)}
                                                    className="text-[#4e5969] hover:text-[#165dff] truncate max-w-[120px]"
                                                >
                                                    {item.name}
                                                </button>
                                            )}
                                        </div>
                                    );
                                });
                            })()}
                        </div>
                    )}
                </div>

                {/* 右侧：AI助手和分享 */}
                <div className="flex shrink-0 items-center gap-3">
                    <Button
                        variant="ghost"
                        className="ai-btn-border-draw h-8 gap-1 rounded-[6px] px-3 font-normal hover:bg-transparent"
                        disabled={isSearching}
                        onClick={onToggleAiAssistant}
                    >
                        <span className="ai-btn-shimmer-overlay" />
                        <AiChatIcon className="size-4" stroke={isSearching ? "#c9cdd4" : "#335cff"} />
                        <span className={isSearching ? '' : 'text-[#000D4D]'}>{localize("com_knowledge.ai_assistant")}</span>
                    </Button>

                    {showShare && (
                        <CopyShareLinkButton
                            sharePath={`/knowledge/share/${space.id}`}
                            label={localize("com_knowledge.share")}
                            successMessage={localize("com_knowledge.share_link_copied")}
                            errorMessage={localize("com_knowledge.copy_failed_retry")}
                        />
                    )}
                </div>
            </div>

            {/* Toolbar：宽屏一行（搜索 + 视图/筛选 + 右侧操作）；窄内容区（宽度小于 TOOLBAR_COMPACT_MAX_WIDTH）两行：仅搜索，其次为视图/筛选与新增/批量 */}
            <div ref={toolbarMeasureRef} className="w-full min-w-0">
                {toolbarCompact ? (
                    <div className="flex flex-col gap-3">
                        <div className={searchFieldClassName}>
                            <CompoundSearchInput
                                spaceId={space.id}
                                isRoot={currentPath.length === 0}
                                onSearch={onSearch}
                            />
                        </div>
                        <div className="flex min-w-0 items-center justify-between gap-2">
                            {viewFilterSortCluster}
                            {batchAndAddActions}
                        </div>
                    </div>
                ) : (
                    <div className="flex min-w-0 items-center justify-between gap-3">
                        <div className="flex min-w-0 flex-1 items-center gap-3">
                            <div className={searchFieldClassName}>
                                <CompoundSearchInput
                                    spaceId={space.id}
                                    isRoot={currentPath.length === 0}
                                    onSearch={onSearch}
                                />
                            </div>
                            {viewFilterSortCluster}
                        </div>
                        {batchAndAddActions}
                    </div>
                )}
            </div>
        </div>
        </>
    );
}
