import {
    ChevronLeft,
    ChevronRight,
    FolderPlus,
    Upload
} from "lucide-react";
import React, { useRef, useState } from "react";
import { FileStatus, FileType, KnowledgeFile, KnowledgeSpace, SortDirection, SortType, SpaceRole } from "~/api/knowledge";
import {
    Breadcrumb,
    BreadcrumbItem, BreadcrumbLink,
    BreadcrumbList,
    BreadcrumbPage, BreadcrumbSeparator,
    Pagination, PaginationContent, PaginationEllipsis, PaginationItem, PaginationLink
} from "~/components";
import { Button } from "~/components/ui/Button";
import { useConfirm, useToastContext } from "~/Providers";
import { copyText } from "~/utils";
import { EditTagsModal } from "./EditTagsModal";
import { FileCard } from "./FileCard";
import { FileTable } from "./FileTable";
import { KnowledgeSpaceHeader } from "./KnowledgeSpaceHeader";

interface KnowledgeSpaceContentProps {
    space: KnowledgeSpace;
    files: KnowledgeFile[];
    currentPage: number;
    pageSize: number;
    total: number;
    onPageChange: (page: number) => void;
    loading: boolean;
    onSearch: (query: string) => void;
    onFilterStatus: (status: FileStatus[]) => void;
    onSort: (sortBy: SortType, direction: SortDirection) => void;
    onNavigateFolder: (folderId?: string) => void;
    onUploadFile: (files?: FileList | File[]) => void;
    onCreateFolder: () => void;
    onDownloadFile: (fileId: string) => void;
    onRenameFile: (fileId: string, newName: string) => void;
    onDeleteFile: (fileId: string) => void;
    onEditTags: (fileId: string) => void;
    onRetryFile: (fileId: string) => void;
    currentPath: Array<{ id?: string; name: string }>;
    onDragStateChange?: (isDragging: boolean, error?: string | null) => void;
    uploadingFiles?: KnowledgeFile[];
    creatingFolder?: any;
    onCancelCreateFolder?: () => void;
    onToggleAiAssistant?: () => void;
    isAiAssistantOpen?: boolean;
}

export function KnowledgeSpaceContent({
    space,
    files,
    currentPage,
    pageSize,
    total,
    onPageChange,
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
    currentPath,
    onDragStateChange,
    uploadingFiles = [],
    creatingFolder,
    onCancelCreateFolder,
    onToggleAiAssistant,
    isAiAssistantOpen
}: KnowledgeSpaceContentProps) {
    const displayFiles = [
        ...(creatingFolder ? [creatingFolder] : []),
        ...uploadingFiles,
        ...files
    ];

    const [searchQuery, setSearchQuery] = useState("");
    const [searchScope, setSearchScope] = useState<"current" | "space">("current");
    const [viewMode, setViewMode] = useState<"card" | "list">("card");
    const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
    const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
    const [sortBy, setSortBy] = useState<SortType>(SortType.UPDATE_TIME);
    const [sortDirection, setSortDirection] = useState<SortDirection>(SortDirection.DESC);
    const [editingTagsFileId, setEditingTagsFileId] = useState<string | null>(null);
    const [isBatchTagging, setIsBatchTagging] = useState(false);

    // Drag and drop state
    const dragCounter = useRef(0);

    // Mock/placeholder for space tags or fetch them
    // In a real scenario, this might come from an API endpoint or context
    const spaceTags = ["国际", "进出口", "大豆油", "政策", "水稻", "粮食", "进口", "出口", "大豆"];

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;

    const { showToast } = useToastContext();
    const confirm = useConfirm();

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
        if (selectedFiles.size === displayFiles.length) {
            setSelectedFiles(new Set());
        } else {
            setSelectedFiles(new Set(displayFiles.map(f => f.id)));
        }
    };

    const handleBatchDownload = () => {
        // TODO: Implement batch download
        console.log("Batch download:", Array.from(selectedFiles));
    };

    const handleBatchTag = () => {
        setIsBatchTagging(true);
    };

    const handleOpenEditTags = (fileId: string) => {
        setEditingTagsFileId(fileId);
        setIsBatchTagging(false);
    };

    const handleCloseEditTags = async (safeClose: boolean) => {
        if (safeClose) {
            setEditingTagsFileId(null);
            setIsBatchTagging(false);
            return;
        }
        const confirmed = await confirm({
            description: "当前标签尚未保存，确认关闭吗？",
            cancelText: "取消",
            confirmText: "确认关闭"
        });
        if (confirmed) {
            setEditingTagsFileId(null);
            setIsBatchTagging(false);
        }
    };

    const handleSaveTags = async (tags: string[]) => {
        if (isBatchTagging) {
            try {
                // Here you'd call an API to add tags to all files in `selectedFiles`
                // e.g., await api.batchAddTags(Array.from(selectedFiles), tags);
                console.log("Batch saving tags for files", Array.from(selectedFiles), "Tags:", tags);

                // Mock success for now: in reality trigger a refresh
                setIsBatchTagging(false);
                setSelectedFiles(new Set());
                showToast({ message: "批量添加标签成功", status: "success" });
            } catch (error) {
                showToast({ message: "批量添加标签失败", status: "error" });
            }
            return;
        }

        if (!editingTagsFileId) return;
        try {
            // Here you'd normally call an API to save the tags to `editingTagsFileId`
            // e.g., await api.updateFileTags(editingTagsFileId, tags);
            console.log("Saving tags for file", editingTagsFileId, "Tags:", tags);
            onEditTags(editingTagsFileId); // Note: might need to adjust props if onEditTags is just a trigger
            setEditingTagsFileId(null);
            showToast({ message: "标签保存成功", status: "success" });
        } catch (error) {
            showToast({ message: "标签保存失败", status: "error" });
        }
    };

    const handleBatchDelete = async () => {
        const confirmed = await confirm({
            title: `确认删除选中的 ${selectedFiles.size} 项内容吗？`,
            description: "包含的文件夹及其子文件也将被一并删除，且不可恢复。",
            cancelText: "取消",
            confirmText: "删除",
            variant: "destructive"
        });

        if (confirmed) {
            // TODO: Implement batch delete API call
            console.log("Batch delete:", Array.from(selectedFiles));
            setSelectedFiles(new Set());
            showToast({ message: "批量删除成功", status: "success" });
        }
    };

    const handleDelete = async (fileId: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        if (!file) return;

        const isFolder = file.type === FileType.FOLDER;

        const confirmed = await confirm({
            title: isFolder ? `确认删除文件夹 “${file.name}” 吗？` : "确认删除当前文件吗？",
            description: isFolder ? "此操作将永久删除该文件夹及其目录下的所有文件，无法撤销。" : undefined,
            cancelText: "取消",
            confirmText: "删除",
            variant: "destructive"
        });

        if (confirmed) {
            onDeleteFile(fileId);
        }
    };

    const handleBatchRetry = () => {
        // Find selected files that have FAILED status
        const failedFileIds = displayFiles
            .filter(f => selectedFiles.has(f.id) && f.status === FileStatus.FAILED)
            .map(f => f.id);

        if (failedFileIds.length > 0) {
            // Trigger retry for each failed file
            failedFileIds.forEach(id => onRetryFile(id));
            console.log("Batch retry triggered for:", failedFileIds);
            showToast({ message: "已开始批量重试", status: "success" });
            setSelectedFiles(new Set());
        }
    };

    const validateFileName = (name: string, isFolder: boolean, currentId: string, isCreating: boolean) => {
        const trimmed = name.trim();
        if (!trimmed) {
            return isFolder && isCreating ? "文件夹名称不能为空" : "名称不能为空";
        }
        if (trimmed.length > 50) {
            return "名称不能超过 50 个字符";
        }

        const duplicate = displayFiles.some(f => f.name === trimmed && f.id !== currentId && (isFolder ? f.type === FileType.FOLDER : f.type !== FileType.FOLDER));
        if (duplicate) {
            return isFolder ? "名称不能与已有文件夹相同" : "名称不能与已有文件相同";
        }
        return null;
    };

    const hasFailedFiles = displayFiles.some(f => selectedFiles.has(f.id) && f.status === FileStatus.FAILED);
    const hasFoldersSelected = displayFiles.some(f => selectedFiles.has(f.id) && f.type === FileType.FOLDER);
    console.log('files :>> ', displayFiles);

    const totalPages = Math.max(1, Math.ceil(total / pageSize));

    const getPageNumbers = () => {
        const pages: (number | 'ellipsis')[] = [];
        if (totalPages <= 5) {
            for (let i = 1; i <= totalPages; i++) {
                pages.push(i);
            }
        } else {
            if (currentPage <= 3) {
                pages.push(1, 2, 3, 4, 'ellipsis', totalPages);
            } else if (currentPage >= totalPages - 2) {
                pages.push(1, 'ellipsis', totalPages - 3, totalPages - 2, totalPages - 1, totalPages);
            } else {
                pages.push(1, 'ellipsis', currentPage - 1, currentPage, currentPage + 1, 'ellipsis', totalPages);
            }
        }
        return pages;
    };

    const validateDragItems = (items: DataTransferItemList) => {
        if (items.length > 50) return "单次最多允许上传 50 个文件";

        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            if (item.kind === 'file') {
                const type = item.type.toLowerCase();

                // Allowed extension mapping to MIME types for drag validation
                const allowedMimeTypes = [
                    'application/pdf',
                    'text/plain',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document', // docx
                    'application/msword', // doc
                    'application/vnd.ms-excel', // xls
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', // xlsx
                    'application/vnd.ms-powerpoint', // ppt
                    'application/vnd.openxmlformats-officedocument.presentationml.presentation', // pptx
                    'text/markdown', 'text/html', 'text/csv',
                    'image/png', 'image/jpeg', 'image/bmp'
                ];

                if (type && !allowedMimeTypes.includes(type)) {
                    return `包含不支持的文件格式 (${type || '未知格式'})`;
                }
            }
        }

        return null;
    };

    const handleDragEnter = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounter.current += 1;
        if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
            const error = validateDragItems(e.dataTransfer.items);
            onDragStateChange?.(true, error);
        }
    };

    const handleDragLeave = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounter.current -= 1;
        if (dragCounter.current === 0) {
            onDragStateChange?.(false);
        }
    };

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
            const error = validateDragItems(e.dataTransfer.items);
            onDragStateChange?.(true, error);
        }
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounter.current = 0;

        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            const filesList = Array.from(e.dataTransfer.files);
            if (filesList.length > 50) {
                onDragStateChange?.(true, "单次最多允许上传 50 个文件");
                onDragStateChange?.(false)
                return;
            }

            for (let f of filesList) {
                if (f.size > 200 * 1024 * 1024) {
                    onDragStateChange?.(true, `文件 ${f.name} 超过 200MB 限制`);
                    setTimeout(() => onDragStateChange?.(false), 2000);
                    return;
                }
                const ext = f.name.split('.').pop()?.toLowerCase();
                if (!ext || !['pdf', 'txt', 'docx', 'ppt', 'pptx', 'md', 'html', 'xls', 'xlsx', 'csv', 'doc', 'png', 'jpg', 'jpeg', 'bmp'].includes(ext)) {
                    onDragStateChange?.(true, `不支持文件 ${f.name} 的格式`);
                    onDragStateChange?.(false)
                    return;
                }
            }

            onDragStateChange?.(false);
            onUploadFile(filesList);
        } else {
            onDragStateChange?.(false);
        }
    };

    return (
        <div
            className="px-4 flex-1 flex flex-col h-full overflow-hidden relative rounded-lg"
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
        >
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
                selectedCount={selectedFiles.size}
                hasFoldersSelected={hasFoldersSelected}
                hasFailedFiles={hasFailedFiles}
                onClearSelection={() => setSelectedFiles(new Set())}
                onBatchDownload={handleBatchDownload}
                onBatchTag={handleBatchTag}
                onBatchRetry={handleBatchRetry}
                onBatchDelete={handleBatchDelete}
                onToggleAiAssistant={onToggleAiAssistant}
                isAiAssistantOpen={isAiAssistantOpen}
            />

            {/* Content Container (Scrollable) */}
            <div className="flex-1 min-w-0 min-h-0 flex flex-col">
                {displayFiles.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center">
                        <div className="text-6xl mb-4">📁</div>
                        <p className="text-[#86909c] mb-4">
                            {searchQuery ? "未找到匹配的文件" : "此位置暂无文件"}
                        </p>
                        {isAdmin && !searchQuery && (
                            <div className="flex gap-2">
                                <Button onClick={() => onUploadFile()}>
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
                    <div className="flex-1 overflow-y-auto">
                        <div className="py-4 grid gap-4 grid-cols-1 min-[480px]:grid-cols-2 min-[600px]:grid-cols-3 min-[768px]:grid-cols-4 min-[1024px]:grid-cols-5 min-[1296px]:grid-cols-6">
                            {displayFiles.map((file) => (
                                <FileCard
                                    key={file.id}
                                    file={file}
                                    userRole={space.role}
                                    isSelected={selectedFiles.has(file.id)}
                                    onSelect={(selected) => handleSelectFile(file.id, selected)}
                                    onDownload={() => onDownloadFile(file.id)}
                                    onRename={(newName) => onRenameFile(file.id, newName)}
                                    onDelete={() => handleDelete(file.id)}
                                    // Use new handler to open modal instead of raw callback
                                    onEditTags={() => handleOpenEditTags(file.id)}
                                    onRetry={file.status === FileStatus.FAILED ? () => onRetryFile(file.id) : undefined}
                                    onValidateName={(newName) => validateFileName(newName, file.type === FileType.FOLDER, file.id, !!file.isCreating)}
                                    onCancelCreate={onCancelCreateFolder}
                                />
                            ))}
                        </div>
                    </div>
                ) : (
                    <div className="flex-1 min-h-0 min-w-0 flex flex-col py-4">
                        <div className="flex-1 overflow-y-auto">
                            <FileTable files={displayFiles}
                                selectedFiles={selectedFiles}
                                handleSelectAll={handleSelectAll}
                                handleSelectFile={handleSelectFile}
                                isAdmin={isAdmin}
                                onDownload={(id) => onDownloadFile(id)}
                                onEditTags={(id) => handleOpenEditTags(id)}
                                onRename={(id, newName) => onRenameFile(id, newName)}
                                onDelete={(id) => handleDelete(id)}
                                onRetry={(id) => onRetryFile(id)}
                                onValidateName={validateFileName}
                                onCancelCreate={onCancelCreateFolder}
                            />
                        </div>
                    </div>
                )}
            </div>

            {/* Footer */}
            <div className="py-3 px-4 flex items-center justify-between border-t border-[#e5e6eb] flex-shrink-0 bg-white">
                <Breadcrumb>
                    <BreadcrumbList>
                        {currentPath.map((path, index) => {
                            const isLast = index === currentPath.length - 1;
                            return (
                                <React.Fragment key={path.id || index}>
                                    <BreadcrumbItem>
                                        {isLast ? (
                                            <BreadcrumbPage className="text-[#1d2129] font-medium">{path.name}</BreadcrumbPage>
                                        ) : (
                                            <BreadcrumbLink
                                                href="#"
                                                onClick={(e) => {
                                                    e.preventDefault();
                                                    onNavigateFolder(path.id);
                                                }}
                                            >
                                                {path.name}
                                            </BreadcrumbLink>
                                        )}
                                    </BreadcrumbItem>
                                    {!isLast && <BreadcrumbSeparator>/</BreadcrumbSeparator>}
                                </React.Fragment>
                            );
                        })}
                    </BreadcrumbList>
                </Breadcrumb>

                {files.length > 0 && (
                    <div className="flex items-center gap-4 text-sm text-[#4e5969]">
                        <div className="flex items-center gap-1">
                            <span>共 <span className="text-[#165dff]">{total}</span> 条数据，</span>
                            <span>每页 {pageSize} 条</span>
                        </div>
                        <Pagination className="mx-0 w-auto">
                            <PaginationContent>
                                <PaginationItem>
                                    <PaginationLink
                                        href="#"
                                        size="icon"
                                        className={"w-6 h-6 " + (currentPage === 1 ? "pointer-events-none opacity-50" : "")}
                                        onClick={(e) => {
                                            e.preventDefault();
                                            if (currentPage > 1) onPageChange(currentPage - 1);
                                        }}
                                    >
                                        <ChevronLeft className="size-4" />
                                    </PaginationLink>
                                </PaginationItem>
                                {getPageNumbers().map((pageNum, idx) => (
                                    <PaginationItem key={idx}>
                                        {pageNum === 'ellipsis' ? (
                                            <PaginationEllipsis />
                                        ) : (
                                            <PaginationLink
                                                href="#"
                                                isActive={pageNum === currentPage}
                                                className={"w-6 h-6 " + (pageNum === currentPage ? "border-primary text-primary" : "")}
                                                onClick={(e) => {
                                                    e.preventDefault();
                                                    onPageChange(pageNum as number);
                                                }}
                                            >
                                                {pageNum}
                                            </PaginationLink>
                                        )}
                                    </PaginationItem>
                                ))}
                                <PaginationItem>
                                    <PaginationLink
                                        href="#"
                                        size="icon"
                                        className={currentPage === totalPages ? "pointer-events-none opacity-50" : ""}
                                        onClick={(e) => {
                                            e.preventDefault();
                                            if (currentPage < totalPages) onPageChange(currentPage + 1);
                                        }}
                                    >
                                        <ChevronRight className="size-4" />
                                    </PaginationLink>
                                </PaginationItem>
                            </PaginationContent>
                        </Pagination>
                    </div>
                )}
            </div>

            {/* Edit Tags Modal */}
            <EditTagsModal
                isOpen={!!editingTagsFileId || isBatchTagging}
                onClose={handleCloseEditTags}
                onSave={handleSaveTags}
                initialTags={isBatchTagging ? [] : files.find(f => f.id === editingTagsFileId)?.tags || []}
                spaceTags={spaceTags}
            />
        </div>
    );
}
