import { useState, useRef } from "react";
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
    onUploadFile: (files?: FileList | File[]) => void;

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
    onUploadFile,
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
    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    const { showToast } = useToastContext();
    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleUploadClick = () => {
        fileInputRef.current?.click();
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
            const filesList = Array.from(e.target.files);

            if (filesList.length > 50) {
                showToast({ message: "单次最多允许上传 50 个文件", status: "error" });
                if (fileInputRef.current) fileInputRef.current.value = "";
                return;
            }

            for (let f of filesList) {
                if (f.size > 200 * 1024 * 1024) {
                    showToast({ message: `文件 ${f.name} 超过 200MB 限制`, status: "error" });
                    if (fileInputRef.current) fileInputRef.current.value = "";
                    return;
                }
                const ext = f.name.split('.').pop()?.toLowerCase();
                if (!ext || !['pdf', 'txt', 'docx', 'ppt', 'pptx', 'md', 'html', 'xls', 'xlsx', 'csv', 'doc', 'png', 'jpg', 'jpeg', 'bmp'].includes(ext)) {
                    showToast({ message: `不支持文件 ${f.name} 的格式`, status: "error" });
                    if (fileInputRef.current) fileInputRef.current.value = "";
                    return;
                }
            }

            onUploadFile(filesList);
            if (fileInputRef.current) fileInputRef.current.value = "";
        }
    };

    const handleShare = () => {
        try {
            const base = window.location.origin + (__APP_ENV__.BASE_URL || "");
            const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
            const shareLink = `${normalizedBase}/knowledge/share/${space.id}`;
            const shareText = `欢迎加入知识空间【${space.name}】 ，点击链接：${shareLink} 一键订阅。`;
            copyText(shareText)
                .then(() => {
                    showToast({ message: "分享链接已复制到粘贴板", status: "success" });
                })
                .catch(() => {
                    showToast({ message: "复制失败，请重试", status: "error" });
                });
        } catch {
            showToast({ message: "复制失败，请重试", status: "error" });
        }
    };
    // Debug log removed during refactoring

    return (
        <div className="pt-5 space-y-4">
            {/* Hidden File Input */}
            <input
                type="file"
                multiple
                className="hidden"
                ref={fileInputRef}
                onChange={handleFileChange}
                accept=".pdf,.txt,.docx,.ppt,.pptx,.md,.html,.xls,.xlsx,.csv,.doc,.png,.jpg,.jpeg,.bmp"
            />
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
                                        <div><span className="text-gray-400">空间描述：</span>
                                            <p>{space.description || "-"}</p>
                                        </div>
                                        <div><span className="text-gray-400">创建人：</span>
                                            <p>{space.creator}</p>
                                        </div>
                                        <div><span className="text-gray-400">加入人数：</span>
                                            <p>{space.memberCount || 0}</p>
                                        </div>
                                        <div><span className="text-gray-400">文件总数：</span>
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
                        AI 助手
                    </Button>

                    <Button
                        variant="ghost"
                        className="h-8 px-1.5 gap-1 transition-colors"
                        onClick={handleShare}
                    >
                        <ShareOutlineIcon className="size-4 text-gray-800" />
                        分享
                    </Button>
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
                                        <div className="px-2 py-1.5 text-xs font-medium text-[#86909c]">状态</div>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.UPLOADING)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.UPLOADING, checked)}
                                        >
                                            上传中
                                        </DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.WAITING)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.WAITING, checked)}
                                        >
                                            排队中
                                        </DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.PROCESSING)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.PROCESSING, checked)}
                                        >
                                            解析中
                                        </DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.REBUILDING)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.REBUILDING, checked)}
                                        >
                                            重建中
                                        </DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.SUCCESS)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.SUCCESS, checked)}
                                        >
                                            成功
                                        </DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.FAILED)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.FAILED, checked)}
                                        >
                                            失败
                                        </DropdownMenuCheckboxItem>
                                        <DropdownMenuCheckboxItem
                                            checked={statusFilter.includes(FileStatus.TIMEOUT)}
                                            onCheckedChange={(checked) => onFilterStatus(FileStatus.TIMEOUT, checked)}
                                        >
                                            超时
                                        </DropdownMenuCheckboxItem>
                                    </DropdownMenuContent>
                                </DropdownMenu>

                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <Button variant="outline" size="icon" className="h-8 font-normal text-gray-700 bg-white border-[#e5e6eb]">
                                            <ArrowDownNarrowWideIcon className="size-4" />
                                        </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="start">
                                        <div className="px-2 py-1.5 text-xs font-medium text-[#86909c]">排序字段</div>
                                        <DropdownMenuItem onClick={() => onSort(SortType.NAME)}>
                                            按名称 {sortBy === SortType.NAME && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem onClick={() => onSort(SortType.TYPE)}>
                                            按类型 {sortBy === SortType.TYPE && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem onClick={() => onSort(SortType.SIZE)}>
                                            按大小 {sortBy === SortType.SIZE && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem onClick={() => onSort(SortType.UPDATE_TIME)}>
                                            按时间 {sortBy === SortType.UPDATE_TIME && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
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
                                            批量操作 <ChevronDown className="size-4 ml-1" />
                                        </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                        <DropdownMenuItem onClick={onBatchDownload} className="cursor-pointer">
                                            <Download className="size-4 mr-2" />
                                            批量下载
                                        </DropdownMenuItem>
                                        {!hasFoldersSelected && (
                                            <DropdownMenuItem onClick={onBatchTag} className="cursor-pointer">
                                                <Tag className="size-4 mr-2" />
                                                批量添加标签
                                            </DropdownMenuItem>
                                        )}
                                        {hasFailedFiles && (
                                            <DropdownMenuItem onClick={onBatchRetry} className="cursor-pointer">
                                                <RotateCcw className="size-4 mr-2" />
                                                批量重试
                                            </DropdownMenuItem>
                                        )}
                                        <DropdownMenuItem onClick={onBatchDelete} className="cursor-pointer text-[#f53f3f] focus:text-[#f53f3f]">
                                            <Trash2 className="size-4 mr-2" />
                                            批量删除
                                        </DropdownMenuItem>
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </>
                        )}
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button size="sm" className="h-8 font-normal rounded-md" disabled={isSearching}>
                                    新增 <ChevronDown className="size-4 ml-1" />
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={onCreateFolder} className="cursor-pointer">
                                    <FolderPlus className="size-4 mr-2" />
                                    新建文件夹
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={handleUploadClick} className="cursor-pointer">
                                    <Upload className="size-4 mr-2" />
                                    上传文件
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                )}
            </div>
        </div>
    );
}
