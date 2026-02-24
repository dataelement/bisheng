import { useState } from "react";
import {
    Search,
    SlidersHorizontal,
    LayoutGrid,
    List,
    Upload,
    FolderPlus,
    Download,
    Tag,
    Trash2,
    RotateCcw,
    ChevronRight,
    Home
} from "lucide-react";
import { KnowledgeSpace, KnowledgeFile, FileStatus, SortType, SortDirection, SpaceRole } from "~/api/knowledge";
import { FileCard } from "~/components/FileCard";
import { FileListRow } from "~/components/FileListRow";
import { cn } from "~/utils";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    DropdownMenuSeparator,
    DropdownMenuCheckboxItem
} from "~/components/ui/DropdownMenu";
import { Button } from "~/components/ui/Button";
import { ArrowUpDown } from "lucide-react";

interface KnowledgeSpaceContentProps {
    space: KnowledgeSpace;
    files: KnowledgeFile[];
    onLoadMore: () => void;
    hasMore: boolean;
    loading: boolean;
    onSearch: (query: string) => void;
    onFilterStatus: (status: FileStatus[]) => void;
    onSort: (sortBy: SortType, direction: SortDirection) => void;
    onNavigateFolder: (folderId?: string) => void;
    onUploadFile: () => void;
    onCreateFolder: () => void;
    onDownloadFile: (fileId: string) => void;
    onRenameFile: (fileId: string) => void;
    onDeleteFile: (fileId: string) => void;
    onEditTags: (fileId: string) => void;
    onRetryFile: (fileId: string) => void;
    currentPath: Array<{ id?: string; name: string }>;
}

export function KnowledgeSpaceContent({
    space,
    files,
    onLoadMore,
    hasMore,
    loading,
    onSearch,
    onFilterStatus,
    onSort,
    onNavigateFolder,
    onUploadFile,
    onCreateFolder,
    onDownloadFile,
    onRenameFile,
    onDeleteFile,
    onEditTags,
    onRetryFile,
    currentPath
}: KnowledgeSpaceContentProps) {
    const [searchQuery, setSearchQuery] = useState("");
    const [searchScope, setSearchScope] = useState<"current" | "space">("current");
    const [viewMode, setViewMode] = useState<"card" | "list">("card");
    const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
    const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
    const [sortBy, setSortBy] = useState<SortType>(SortType.UPDATE_TIME);
    const [sortDirection, setSortDirection] = useState<SortDirection>(SortDirection.DESC);

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;

    const handleSearch = (query: string) => {
        setSearchQuery(query);
        onSearch(query);
    };

    const handleStatusFilter = (status: FileStatus, checked: boolean) => {
        const newFilter = checked
            ? [...statusFilter, status]
            : statusFilter.filter(s => s !== status);
        setStatusFilter(newFilter);
        onFilterStatus(newFilter);
    };

    const handleSort = (newSortBy: SortType) => {
        const newDirection = sortBy === newSortBy && sortDirection === SortDirection.ASC
            ? SortDirection.DESC
            : SortDirection.ASC;
        setSortBy(newSortBy);
        setSortDirection(newDirection);
        onSort(newSortBy, newDirection);
    };

    const handleSelectFile = (fileId: string, selected: boolean) => {
        const newSelected = new Set(selectedFiles);
        if (selected) {
            newSelected.add(fileId);
        } else {
            newSelected.delete(fileId);
        }
        setSelectedFiles(newSelected);
    };

    const handleSelectAll = () => {
        if (selectedFiles.size === files.length) {
            setSelectedFiles(new Set());
        } else {
            setSelectedFiles(new Set(files.map(f => f.id)));
        }
    };

    const handleBatchDownload = () => {
        // TODO: Implement batch download
        console.log("Batch download:", Array.from(selectedFiles));
    };

    const handleBatchTag = () => {
        // TODO: Implement batch tag
        console.log("Batch tag:", Array.from(selectedFiles));
    };

    const handleBatchDelete = () => {
        // TODO: Implement batch delete
        console.log("Batch delete:", Array.from(selectedFiles));
    };

    const handleBatchRetry = () => {
        // TODO: Implement batch retry
        console.log("Batch retry:", Array.from(selectedFiles));
    };

    const hasFailedFiles = files.some(f => selectedFiles.has(f.id) && f.status === FileStatus.FAILED);

    return (
        <div className="flex-1 flex flex-col bg-[#f7f8fa] h-screen overflow-hidden">
            {/* Header */}
            <div className="bg-white border-b border-[#e5e6eb] p-4">
                {/* Breadcrumb */}
                <div className="flex items-center gap-1 mb-3 text-sm">
                    <button
                        onClick={() => onNavigateFolder(undefined)}
                        className="flex items-center gap-1 text-[#4e5969] hover:text-[#165dff]"
                    >
                        <Home className="size-4" />
                    </button>
                    {currentPath.map((item, index) => (
                        <div key={index} className="flex items-center gap-1">
                            <ChevronRight className="size-4 text-[#86909c]" />
                            {index === currentPath.length - 1 ? (
                                <span className="text-[#1d2129] font-medium">{item.name}</span>
                            ) : (
                                <button
                                    onClick={() => onNavigateFolder(item.id)}
                                    className="text-[#4e5969] hover:text-[#165dff]"
                                >
                                    {item.name}
                                </button>
                            )}
                        </div>
                    ))}
                </div>

                {/* Toolbar */}
                <div className="flex items-center gap-3">
                    {/* Search */}
                    <div className="flex-1 flex items-center gap-2">
                        <div className="relative flex-1 max-w-md">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#86909c]" />
                            <input
                                type="text"
                                placeholder={searchScope === "current" ? "搜索当前位置" : "搜索整个空间"}
                                value={searchQuery}
                                onChange={(e) => handleSearch(e.target.value)}
                                className="w-full pl-9 pr-3 py-2 border border-[#e5e6eb] rounded focus:outline-none focus:border-[#165dff]"
                            />
                        </div>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button variant="outline" size="sm">
                                    {searchScope === "current" ? "当前位置" : "整个空间"}
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent>
                                <DropdownMenuItem onClick={() => setSearchScope("current")}>
                                    当前位置
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => setSearchScope("space")}>
                                    整个空间
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>

                    {/* Filters & Sort */}
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <Button variant="outline" size="sm">
                                <SlidersHorizontal className="size-4 mr-1" />
                                筛选
                            </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <div className="px-2 py-1.5 text-xs font-medium text-[#86909c]">状态</div>
                            <DropdownMenuCheckboxItem
                                checked={statusFilter.includes(FileStatus.SUCCESS)}
                                onCheckedChange={(checked) => handleStatusFilter(FileStatus.SUCCESS, checked)}
                            >
                                成功
                            </DropdownMenuCheckboxItem>
                            <DropdownMenuCheckboxItem
                                checked={statusFilter.includes(FileStatus.PROCESSING)}
                                onCheckedChange={(checked) => handleStatusFilter(FileStatus.PROCESSING, checked)}
                            >
                                处理中
                            </DropdownMenuCheckboxItem>
                            <DropdownMenuCheckboxItem
                                checked={statusFilter.includes(FileStatus.FAILED)}
                                onCheckedChange={(checked) => handleStatusFilter(FileStatus.FAILED, checked)}
                            >
                                失败
                            </DropdownMenuCheckboxItem>
                            <DropdownMenuSeparator />
                            <div className="px-2 py-1.5 text-xs font-medium text-[#86909c]">排序</div>
                            <DropdownMenuItem onClick={() => handleSort(SortType.NAME)}>
                                按名称 {sortBy === SortType.NAME && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => handleSort(SortType.TYPE)}>
                                按类型 {sortBy === SortType.TYPE && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => handleSort(SortType.SIZE)}>
                                按大小 {sortBy === SortType.SIZE && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => handleSort(SortType.UPDATE_TIME)}>
                                按时间 {sortBy === SortType.UPDATE_TIME && (sortDirection === SortDirection.ASC ? "↑" : "↓")}
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>

                    {/* View Mode */}
                    <div className="flex border border-[#e5e6eb] rounded">
                        <button
                            onClick={() => setViewMode("card")}
                            className={cn(
                                "p-2",
                                viewMode === "card" ? "bg-[#e8f3ff] text-[#165dff]" : "text-[#86909c] hover:bg-[#f7f8fa]"
                            )}
                        >
                            <LayoutGrid className="size-4" />
                        </button>
                        <button
                            onClick={() => setViewMode("list")}
                            className={cn(
                                "p-2",
                                viewMode === "list" ? "bg-[#e8f3ff] text-[#165dff]" : "text-[#86909c] hover:bg-[#f7f8fa]"
                            )}
                        >
                            <List className="size-4" />
                        </button>
                    </div>

                    {/* Actions */}
                    {isAdmin && (
                        <>
                            <Button onClick={onUploadFile} size="sm">
                                <Upload className="size-4 mr-1" />
                                上传
                            </Button>
                            <Button onClick={onCreateFolder} variant="outline" size="sm">
                                <FolderPlus className="size-4 mr-1" />
                                新建文件夹
                            </Button>
                        </>
                    )}
                </div>
            </div>

            {/* Batch Operations Toolbar */}
            {selectedFiles.size > 0 && (
                <div className="bg-[#e8f3ff] border-b border-[#165dff] px-4 py-2 flex items-center gap-3">
                    <span className="text-sm text-[#1d2129]">
                        已选择 <span className="font-medium">{selectedFiles.size}</span> 项
                    </span>
                    <div className="flex-1" />
                    <Button variant="outline" size="sm" onClick={handleBatchDownload}>
                        <Download className="size-4 mr-1" />
                        下载
                    </Button>
                    {isAdmin && (
                        <>
                            <Button variant="outline" size="sm" onClick={handleBatchTag}>
                                <Tag className="size-4 mr-1" />
                                添加标签
                            </Button>
                            {hasFailedFiles && (
                                <Button variant="outline" size="sm" onClick={handleBatchRetry}>
                                    <RotateCcw className="size-4 mr-1" />
                                    重试
                                </Button>
                            )}
                            <Button variant="outline" size="sm" onClick={handleBatchDelete}>
                                <Trash2 className="size-4 mr-1 text-[#f53f3f]" />
                                <span className="text-[#f53f3f]">删除</span>
                            </Button>
                        </>
                    )}
                    <Button variant="ghost" size="sm" onClick={() => setSelectedFiles(new Set())}>
                        取消
                    </Button>
                </div>
            )}

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4">
                {files.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center">
                        <div className="text-6xl mb-4">📁</div>
                        <p className="text-[#86909c] mb-4">
                            {searchQuery ? "未找到匹配的文件" : "此位置暂无文件"}
                        </p>
                        {isAdmin && !searchQuery && (
                            <div className="flex gap-2">
                                <Button onClick={onUploadFile}>
                                    <Upload className="size-4 mr-1" />
                                    上传文件
                                </Button>
                                <Button onClick={onCreateFolder} variant="outline">
                                    <FolderPlus className="size-4 mr-1" />
                                    新建文件夹
                                </Button>
                            </div>
                        )}
                    </div>
                ) : viewMode === "card" ? (
                    <div className="grid grid-cols-4 gap-4">
                        {files.map((file) => (
                            <FileCard
                                key={file.id}
                                file={file}
                                userRole={space.role}
                                isSelected={selectedFiles.has(file.id)}
                                onSelect={(selected) => handleSelectFile(file.id, selected)}
                                onDownload={() => onDownloadFile(file.id)}
                                onRename={() => onRenameFile(file.id)}
                                onDelete={() => onDeleteFile(file.id)}
                                onEditTags={() => onEditTags(file.id)}
                                onRetry={file.status === FileStatus.FAILED ? () => onRetryFile(file.id) : undefined}
                            />
                        ))}
                    </div>
                ) : (
                    <div className="bg-white rounded border border-[#e5e6eb]">
                        {/* Table Header */}
                        <div className="flex items-center px-4 py-3 border-b border-[#e5e6eb] bg-[#f7f8fa] text-sm font-medium text-[#4e5969]">
                            {/* 复选框 */}
                            <div className="w-12 flex items-center justify-center">
                                <input
                                    type="checkbox"
                                    checked={selectedFiles.size === files.length && files.length > 0}
                                    onChange={handleSelectAll}
                                    className="size-4"
                                />
                            </div>

                            {/* 文件名 */}
                            <button
                                className="flex-1 flex items-center gap-1 hover:text-[#165dff] text-left"
                                onClick={() => handleSort(SortType.NAME)}
                            >
                                <span>文件名</span>
                                {sortBy === SortType.NAME && (
                                    <span className="text-[#165dff]">
                                        {sortDirection === SortDirection.ASC ? "↑" : "↓"}
                                    </span>
                                )}
                            </button>

                            {/* 文件类型 */}
                            <button
                                className="w-28 flex items-center gap-1 hover:text-[#165dff]"
                                onClick={() => handleSort(SortType.TYPE)}
                            >
                                <span>文件类型</span>
                                {sortBy === SortType.TYPE && (
                                    <span className="text-[#165dff]">
                                        {sortDirection === SortDirection.ASC ? "↑" : "↓"}
                                    </span>
                                )}
                            </button>

                            {/* 文件大小 */}
                            <button
                                className="w-32 flex items-center gap-1 hover:text-[#165dff]"
                                onClick={() => handleSort(SortType.SIZE)}
                            >
                                <span>文件大小</span>
                                {sortBy === SortType.SIZE && (
                                    <span className="text-[#165dff]">
                                        {sortDirection === SortDirection.ASC ? "↑" : "↓"}
                                    </span>
                                )}
                            </button>

                            {/* 标签 */}
                            <div className="w-48">标签</div>

                            {/* 更新时间 */}
                            <button
                                className="w-48 flex items-center gap-1 hover:text-[#165dff]"
                                onClick={() => handleSort(SortType.UPDATE_TIME)}
                            >
                                <span>更新时间</span>
                                {sortBy === SortType.UPDATE_TIME && (
                                    <span className="text-[#165dff]">
                                        {sortDirection === SortDirection.ASC ? "↑" : "↓"}
                                    </span>
                                )}
                            </button>

                            {/* 状态 */}
                            <div className="w-24">状态</div>

                            {/* 操作 */}
                            <div className="w-24 text-right">操作</div>
                        </div>

                        {/* Table Body */}
                        <div>
                            {files.map((file) => (
                                <FileListRow
                                    key={file.id}
                                    file={file}
                                    userRole={space.role}
                                    isSelected={selectedFiles.has(file.id)}
                                    onSelect={(selected) => handleSelectFile(file.id, selected)}
                                    onDownload={() => onDownloadFile(file.id)}
                                    onRename={() => onRenameFile(file.id)}
                                    onDelete={() => onDeleteFile(file.id)}
                                    onEditTags={() => onEditTags(file.id)}
                                    onRetry={file.status === FileStatus.FAILED ? () => onRetryFile(file.id) : undefined}
                                />
                            ))}
                        </div>
                    </div>
                )}

                {/* Load More */}
                {hasMore && (
                    <div className="flex justify-center mt-6">
                        <Button
                            onClick={onLoadMore}
                            variant="outline"
                            disabled={loading}
                        >
                            {loading ? "加载中..." : "加载更多"}
                        </Button>
                    </div>
                )}
            </div>
        </div>
    );
}
