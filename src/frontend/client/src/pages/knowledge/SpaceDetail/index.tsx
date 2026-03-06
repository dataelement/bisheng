import {
    Download,
    FolderPlus,
    RotateCcw,
    Tag,
    Trash2,
    Upload
} from "lucide-react";
import { useState } from "react";
import { FileStatus, KnowledgeFile, KnowledgeSpace, SortDirection, SortType, SpaceRole } from "~/api/knowledge";
import { FileListRow } from "~/components/FileListRow";
import { Button } from "~/components/ui/Button";
import { useToastContext } from "~/Providers";
import { copyText } from "~/utils";
import { FileCard } from "./FileCard";
import { KnowledgeSpaceHeader } from "./KnowledgeSpaceHeader";
import { FileTable } from "./FileTable";

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

    const { showToast } = useToastContext();

    const handleShare = () => {
        const shareText = `欢迎加入知识空间【${space.name}】`;
        copyText(shareText).then(() => {
            showToast({ message: '分享链接已复制到粘贴板', status: 'success' });
        }).catch(() => {
            showToast({ message: '复制失败，请重试', status: 'error' });
        });
    };

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
    console.log('files :>> ', files);

    return (
        <div className="px-4 flex-1 flex flex-col h-full overflow-hidden">
            {/* Header */}
            <KnowledgeSpaceHeader
                space={space}
                currentPath={currentPath}
                onNavigateFolder={onNavigateFolder}
                searchQuery={searchQuery}
                onSearch={handleSearch}
                viewMode={viewMode}
                setViewMode={setViewMode}
                statusFilter={statusFilter}
                onFilterStatus={handleStatusFilter}
                sortBy={sortBy}
                sortDirection={sortDirection}
                onSort={handleSort}
                onCreateFolder={onCreateFolder}
                onUploadFile={onUploadFile}
            />

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
            <div className="flex-1">
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
                    <div className="overflow-y-auto py-4 grid gap-4 grid-cols-1 min-[480px]:grid-cols-2 min-[600px]:grid-cols-3 min-[768px]:grid-cols-4 min-[1024px]:grid-cols-5 min-[1296px]:grid-cols-6">
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
                    <div className="py-4">
                        <FileTable files={files}
                            selectedFiles={selectedFiles}
                            handleSelectAll={handleSelectAll}
                            handleSelectFile={handleSelectFile}
                            isAdmin={isAdmin}
                            onDownload={(id) => onDownloadFile(id)}
                            onEditTags={(id) => onEditTags(id)}
                            onRename={(id) => onRenameFile(id)}
                            onDelete={(id) => onDeleteFile(id)}
                            onRetry={(id) => onRetryFile(id)}
                        />
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
