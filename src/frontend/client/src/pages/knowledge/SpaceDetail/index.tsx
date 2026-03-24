import {
    FolderPlus,
    Upload
} from "lucide-react";
import React, { useState } from "react";
import { FileStatus, FileType, KnowledgeFile, KnowledgeSpace, SortDirection, SortType, SpaceRole, batchDownloadApi, batchDeleteApi, batchRetryApi } from "~/api/knowledge";
import { SearchParams } from "./CompoundSearchInput";
import { Button } from "~/components/ui/Button";
import { useConfirm, useToastContext } from "~/Providers";
import { EditTagsModal } from "./EditTagsModal";
import { FileCard } from "./FileCard";
import { FileTable } from "./FileTable";
import { KnowledgeSpaceHeader } from "./KnowledgeSpaceHeader";
import { PaginationBar } from "./PaginationBar";
import { SelectionPathBreadcrumb } from "./SelectionPathBreadcrumb";
import { useFileDragDrop } from "../hooks/useFileDragDrop";
import { triggerUrlDownload } from "../knowledgeUtils";

interface KnowledgeSpaceContentProps {
    space: KnowledgeSpace;
    files: KnowledgeFile[];
    currentPage: number;
    pageSize: number;
    total: number;
    onPageChange: (page: number) => void;
    loading: boolean;
    onSearch: (params: SearchParams) => void;
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
    creatingFolder?: KnowledgeFile | null;
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
    const [searchTagIds, setSearchTagIds] = useState<number[]>([]);
    const [viewMode, setViewModeState] = useState<"card" | "list">(() => {
        const saved = localStorage.getItem("knowledge-view-mode");
        return saved === "list" || saved === "card" ? saved : "card";
    });
    const setViewMode = (mode: "card" | "list") => {
        setViewModeState(mode);
        localStorage.setItem("knowledge-view-mode", mode);
    };
    const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
    const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
    const [sortBy, setSortBy] = useState<SortType>(SortType.UPDATE_TIME);
    const [sortDirection, setSortDirection] = useState<SortDirection>(SortDirection.DESC);
    const [editingTagsFileId, setEditingTagsFileId] = useState<string | null>(null);
    const [isBatchTagging, setIsBatchTagging] = useState(false);

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    const isSearching = searchQuery.trim().length > 0 || searchTagIds.length > 0;

    const { showToast } = useToastContext();
    const confirm = useConfirm();

    // ─── Drag and drop ──────────────────────────────────────────────────
    const { handleDragEnter, handleDragLeave, handleDragOver, handleDrop } = useFileDragDrop({
        onDragStateChange,
        onUploadFile,
    });

    const handleSearch = (params: SearchParams) => {
        setSearchQuery(params.keyword);
        setSearchTagIds(params.tagIds);
        setSelectedFiles(new Set());
        onSearch(params);
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

    const handleBatchDownload = async () => {
        const selectedList = displayFiles.filter(f => selectedFiles.has(f.id));
        const fileIds = selectedList.filter(f => f.type !== FileType.FOLDER).map(f => Number(f.id));
        const folderIds = selectedList.filter(f => f.type === FileType.FOLDER).map(f => Number(f.id));
        try {
            const url = await batchDownloadApi(space.id, {
                file_ids: fileIds.length ? fileIds : undefined,
                folder_ids: folderIds.length ? folderIds : undefined,
            });
            if (!url) { showToast({ message: "下载链接获取失败", status: "error" }); return; }
            triggerUrlDownload(url, `download_${Date.now()}.zip`);
        } catch {
            showToast({ message: "下载失败", status: "error" });
        }
    };

    const handleBatchTag = () => {
        setIsBatchTagging(true);
    };

    const handleSingleDownload = async (fileId: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        const isFolder = file?.type === FileType.FOLDER;
        const id = Number(fileId);
        try {
            const url = await batchDownloadApi(space.id, {
                file_ids: isFolder ? undefined : [id],
                folder_ids: isFolder ? [id] : undefined,
            });
            if (!url) { showToast({ message: "下载链接获取失败", status: "error" }); return; }
            triggerUrlDownload(url, file?.name);
        } catch {
            showToast({ message: "下载失败", status: "error" });
        }
    };

    const handlePreviewFile = (fileId: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        const fileName = file?.name || "未知文件";
        const fileType = file?.type || "";
        const url = `${__APP_ENV__.BASE_URL}/knowledge/file/${fileId}?name=${encodeURIComponent(fileName)}&type=${encodeURIComponent(fileType)}&spaceId=${encodeURIComponent(space.id)}`;
        window.open(url, '_blank');
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

    // Called after tags are saved successfully — refresh file list
    const handleTagsSaved = () => {
        setEditingTagsFileId(null);
        setIsBatchTagging(false);
        setSelectedFiles(new Set());
        // Trigger a refresh of the file list from parent
        onEditTags(editingTagsFileId || "");
    };

    const handleBatchDelete = async () => {
        const confirmed = await confirm({
            title: `确认删除选中的 ${selectedFiles.size} 项内容吗？`,
            description: "包含的文件夹及其子文件也将被一并删除，且不可恢复。",
            cancelText: "取消",
            confirmText: "删除",
            variant: "destructive"
        });

        if (!confirmed) return;

        const selectedList = displayFiles.filter(f => selectedFiles.has(f.id));
        const fileIds = selectedList.filter(f => f.type !== FileType.FOLDER).map(f => Number(f.id));
        const folderIds = selectedList.filter(f => f.type === FileType.FOLDER).map(f => Number(f.id));

        try {
            await batchDeleteApi(space.id, {
                file_ids: fileIds.length ? fileIds : undefined,
                folder_ids: folderIds.length ? folderIds : undefined,
            });
            setSelectedFiles(new Set());
            showToast({ message: "批量删除成功", status: "success" });
            // Notify parent to refresh the list
            onDeleteFile("");
        } catch {
            showToast({ message: "批量删除失败", status: "error" });
        }
    };

    const handleDelete = async (fileId: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        if (!file) return;

        const isFolder = file.type === FileType.FOLDER;

        const confirmed = await confirm({
            title: isFolder ? `确认删除文件夹 "${file.name}" 吗？` : "确认删除当前文件吗？",
            description: isFolder ? "此操作将永久删除该文件夹及其目录下的所有文件，无法撤销。" : undefined,
            cancelText: "取消",
            confirmText: "删除",
            variant: "destructive"
        });

        if (confirmed) {
            onDeleteFile(fileId);
        }
    };

    const handleBatchRetry = async () => {
        // Find selected files/folders that have FAILED status or partial failures
        const retryIds = displayFiles
            .filter(f => selectedFiles.has(f.id) && (
                f.status === FileStatus.FAILED ||
                (f.successFileNum !== undefined && f.fileNum !== undefined && f.successFileNum < f.fileNum)
            ))
            .map(f => Number(f.id));

        if (retryIds.length === 0) return;

        try {
            await batchRetryApi(space.id, retryIds);
            showToast({ message: "已开始批量重试", status: "success" });
            setSelectedFiles(new Set());
            // Refresh list
            onDeleteFile("");
        } catch {
            showToast({ message: "批量重试失败", status: "error" });
        }
    };

    const handleSingleRetry = async (fileId: string) => {
        try {
            await batchRetryApi(space.id, [Number(fileId)]);
            showToast({ message: "已开始重试", status: "success" });
            // Refresh list
            onDeleteFile("");
        } catch {
            showToast({ message: "重试失败", status: "error" });
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
                isSearching={isSearching}
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
                                    onDownload={() => handleSingleDownload(file.id)}
                                    onRename={(newName) => onRenameFile(file.id, newName)}
                                    onDelete={() => handleDelete(file.id)}
                                    onEditTags={() => handleOpenEditTags(file.id)}
                                    onRetry={() => handleSingleRetry(file.id)}
                                    onNavigateFolder={() => onNavigateFolder(file.id)}
                                    onPreview={handlePreviewFile}
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
                                onDownload={(id) => handleSingleDownload(id)}
                                onEditTags={(id) => handleOpenEditTags(id)}
                                onRename={(id, newName) => onRenameFile(id, newName)}
                                onDelete={(id) => handleDelete(id)}
                                onRetry={(id) => handleSingleRetry(id)}
                                onNavigateFolder={(id) => onNavigateFolder(id)}
                                onPreview={(id) => handlePreviewFile(id)}
                                onValidateName={validateFileName}
                                onCancelCreate={onCancelCreateFolder}
                                sortBy={sortBy}
                                sortDirection={sortDirection}
                                onSort={handleSort}
                            />
                        </div>
                    </div>
                )}
            </div>

            {/* Footer */}
            <div className="py-3 px-4 flex items-center justify-between border-t border-[#e5e6eb] flex-shrink-0 bg-white">
                {/* Left side: selection path (only in search mode with selections) */}
                {isSearching && selectedFiles.size > 0 ? (
                    <SelectionPathBreadcrumb
                        spaceId={space.id}
                        spaceName={space.name}
                        selectedFiles={selectedFiles}
                        displayFiles={displayFiles}
                    />
                ) : (
                    <div />
                )}

                {files.length > 0 && (
                    <PaginationBar
                        currentPage={currentPage}
                        pageSize={pageSize}
                        total={total}
                        onPageChange={onPageChange}
                    />
                )}
            </div>

            {/* Edit Tags Modal */}
            <EditTagsModal
                isOpen={!!editingTagsFileId || isBatchTagging}
                onClose={handleCloseEditTags}
                onSaved={handleTagsSaved}
                spaceId={space.id}
                fileId={isBatchTagging ? null : editingTagsFileId}
                fileIds={isBatchTagging ? Array.from(selectedFiles) : undefined}
                initialTagIds={
                    editingTagsFileId && !isBatchTagging
                        ? (displayFiles.find(f => f.id === editingTagsFileId)?.tags?.map(t => t.id) || [])
                        : []
                }
            />
        </div>
    );
}
