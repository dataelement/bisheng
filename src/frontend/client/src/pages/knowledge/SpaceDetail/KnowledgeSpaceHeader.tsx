import {
    LayoutGrid,
    List,
    Upload,
    FolderPlus,
    ChevronDown,
    ChevronRight,
    Home,
    Info,
    ArrowDownNarrowWideIcon,
    FunnelIcon,
    Download,
    Tag,
    RotateCcw,
    Trash2
} from "lucide-react";
import { KnowledgeSpace, FileStatus, SortType, SortDirection, SpaceRole } from "~/api/knowledge";
import { cn, copyText } from "~/utils";
import { CompoundSearchInput, SearchParams } from "./CompoundSearchInput";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    DropdownMenuSeparator,
    DropdownMenuCheckboxItem
} from "~/components/ui/DropdownMenu";
import { Button } from "~/components/ui/Button";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { ShareOutlineIcon, AiChatIcon } from "~/components/icons";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";

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
    sortBy: SortType;
    sortDirection: SortDirection;
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
    onToggleAiAssistant?: () => void;
    isAiAssistantOpen?: boolean;
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
    onToggleAiAssistant,
    isAiAssistantOpen
}: KnowledgeSpaceHeaderProps) {
    const localize = useLocalize();
    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    const { showToast } = useToastContext();

    const handleShare = () => {
        try {
            const base = window.location.origin + (__APP_ENV__.BASE_URL || "");
            const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
            const shareLink = `${normalizedBase}/knowledge/share/${space.id}`;
            const shareText = localize("com_knowledge.welcome_join_space_link", { 0: space.name, 1: shareLink });
            copyText(shareText)
                .then(() => {
                    showToast({ message: localize("com_knowledge.share_link_copied"), status: "success" });
                })
                .catch(() => {
                    showToast({ message: localize("com_knowledge.copy_failed_retry"), status: "error" });
                });
        } catch {
            showToast({ message: localize("com_knowledge.copy_failed_retry"), status: "error" });
        }
    };
    // Debug log removed during refactoring

    return (
        <div className="pt-5 space-y-4">
            {/* 面包屑 / Title */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                {/* 左侧：标题与信息 / 面包屑 */}
                <div className="flex items-center gap-1 text-sm flex-wrap w-full sm:w-auto">
                    {currentPath.length === 0 ? (
                        <div className="flex items-center gap-1">
                            <h1 className="text-base text-[#1d2129]">{space.name}</h1>
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
                <div className="flex items-center gap-3 self-end sm:self-auto shrink-0 mt-2 sm:mt-0">
                    <Button
                        variant="ghost"
                        className={`h-8 px-1.5 gap-1 bg-gradient-to-br from-[#335CFF] to-[#7433FF] bg-clip-text text-transparent hover:text-transparent ${isAiAssistantOpen ? 'bg-[#f0f5ff] rounded-md' : ''}`}
                        disabled={isSearching}
                        onClick={onToggleAiAssistant}
                    >
                        <AiChatIcon className="size-3.5" stroke={isSearching ? "#c9cdd4" : "#335CFF"} />
                        {localize("com_knowledge.ai_assistant")}</Button>

                    <Button
                        variant="ghost"
                        className="h-8 px-1.5 gap-1 transition-colors"
                        onClick={handleShare}
                    >
                        <ShareOutlineIcon className="size-4 text-gray-800" />
                        {localize("com_knowledge.share")}</Button>
                </div>
            </div>

            {/* Toolbar */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                {/* { Left side: search & toggle & filter } */}
                <div className="flex flex-col sm:flex-row sm:items-center gap-3 w-full sm:w-auto">
                    {/* Search */}
                    <div className="flex-1 sm:flex-none flex items-center gap-2 w-full sm:w-auto">
                        <div className="relative flex-1 sm:flex-none sm:w-[450px]">
                            <CompoundSearchInput
                                spaceId={space.id}
                                isRoot={currentPath.length === 0}
                                onSearch={onSearch}
                            />
                        </div>
                    </div>

                    <div className="flex items-center gap-3 w-full sm:w-auto">
                        {/* View Mode & Extra drop (Placeholder for bulk operations if needed, currently view mode) */}
                        <div className="flex border rounded-md p-0.5 text-sm h-8 shrink-0">
                            <button
                                onClick={() => setViewMode("list")}
                                className={cn(
                                    "px-2.5 flex items-center justify-center transition-colors rounded",
                                    viewMode === "list" ? "bg-primary/15 text-primary" : "text-[#4e5969] hover:bg-[#f2f3f5]"
                                )}
                            >
                                <List className="size-4" />
                            </button>
                            <button
                                onClick={() => setViewMode("card")}
                                className={cn(
                                    "px-2.5 flex items-center justify-center transition-colors rounded",
                                    viewMode === "card" ? "bg-primary/15 text-primary" : "text-[#4e5969] hover:bg-[#f2f3f5]"
                                )}
                            >
                                <LayoutGrid className="size-4" />
                            </button>
                        </div>

                        {/* Filters & Sort */}
                        {viewMode === "card" && (
                            <>
                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <Button variant="outline" size="icon" className="h-8 font-normal text-gray-700 bg-white border-[#e5e6eb]">
                                            <FunnelIcon className="size-4" />
                                        </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="start">
                                        <div className="px-2 py-1.5 text-xs font-medium text-[#86909c]">{localize("com_knowledge.status")}</div>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.UPLOADING)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.UPLOADING, checked)}
                                        >
                                            {localize("com_knowledge.uploading_status")}</DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.WAITING)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.WAITING, checked)}
                                        >
                                            {localize("com_knowledge.queueing_status")}</DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.PROCESSING)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.PROCESSING, checked)}
                                        >
                                            {localize("com_knowledge.parsing_status")}</DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.REBUILDING)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.REBUILDING, checked)}
                                        >
                                            {localize("com_knowledge.rebuilding_status")}</DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.SUCCESS)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.SUCCESS, checked)}
                                        >
                                            {localize("com_knowledge.success")}</DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.FAILED)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.FAILED, checked)}
                                        >
                                            {localize("com_knowledge.fail")}</DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.TIMEOUT)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.TIMEOUT, checked)}
                                        >
                                            {localize("com_knowledge.timeout")}</DropdownMenuCheckboxItem>
                                    </DropdownMenuContent>
                                </DropdownMenu>

                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <Button variant="outline" size="icon" className="h-8 font-normal text-gray-700 bg-white border-[#e5e6eb]">
                                            <ArrowDownNarrowWideIcon className="size-4" />
                                        </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="start">
                                        <div className="px-2 py-1.5 text-xs font-medium text-[#86909c]">{localize("com_knowledge.sort_field")}</div>
                                        <DropdownMenuItem onClick={() => onSort(SortType.NAME)}>
                                            {localize("com_knowledge.sort_by_name")}{sortBy === SortType.NAME && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem onClick={() => onSort(SortType.TYPE)}>
                                            {localize("com_knowledge.sort_by_type")}{sortBy === SortType.TYPE && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem onClick={() => onSort(SortType.SIZE)}>
                                            {localize("com_knowledge.sort_by_size")}{sortBy === SortType.SIZE && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem onClick={() => onSort(SortType.UPDATE_TIME)}>
                                            {localize("com_knowledge.sort_by_time")}{sortBy === SortType.UPDATE_TIME && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                                        </DropdownMenuItem>
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </>
                        )}
                    </div>
                </div>

                {/* Actions */}
                {isAdmin && (
                    <div className="flex items-center gap-2 self-end sm:self-auto shrink-0 mt-2 sm:mt-0">
                        {selectedCount > 1 && (
                            <>
                                {/* <Button variant="ghost" size="sm" className="h-8 font-normal text-[#4e5969]" onClick={onClearSelection}>
                                    取消选择
                                </Button> */}
                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <Button size="sm" variant="outline" className="h-8 font-normal rounded-md border-[#e5e6eb] text-[#4e5969]" disabled={isSearching}>
                                            {localize("com_knowledge.batch_operation")}<ChevronDown className="size-4 ml-1" />
                                        </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                        <DropdownMenuItem onClick={onBatchDownload} className="cursor-pointer">
                                            <Download className="size-4 mr-2" />
                                            {localize("com_knowledge.batch_download")}</DropdownMenuItem>
                                        {!hasFoldersSelected && (
                                            <DropdownMenuItem onClick={onBatchTag} className="cursor-pointer">
                                                <Tag className="size-4 mr-2" />
                                                {localize("com_knowledge.batch_add_tags")}</DropdownMenuItem>
                                        )}
                                        {hasFailedFiles && (
                                            <DropdownMenuItem onClick={onBatchRetry} className="cursor-pointer">
                                                <RotateCcw className="size-4 mr-2" />
                                                {localize("com_knowledge.batch_retry")}</DropdownMenuItem>
                                        )}
                                        <DropdownMenuItem onClick={onBatchDelete} className="cursor-pointer text-[#f53f3f] focus:text-[#f53f3f]">
                                            <Trash2 className="size-4 mr-2" />
                                            {localize("com_knowledge.batch_delete")}</DropdownMenuItem>
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </>
                        )}
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button size="sm" className="h-8 font-normal rounded-md" disabled={isSearching}>
                                    {localize("com_knowledge.add_new")}<ChevronDown className="size-4 ml-1" />
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={onCreateFolder} className="cursor-pointer">
                                    <FolderPlus className="size-4 mr-2" />
                                    {localize("com_knowledge.new_folder")}</DropdownMenuItem>
                                <DropdownMenuItem onClick={onTriggerUpload} className="cursor-pointer">
                                    <Upload className="size-4 mr-2" />
                                    {localize("com_knowledge.upload_file")}</DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                )}
            </div>
        </div>
    );
}
