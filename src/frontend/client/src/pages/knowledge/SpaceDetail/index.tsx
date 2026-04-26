import { useState, useRef, useEffect, useLayoutEffect } from "react";
import { useRecoilValue } from "recoil";
import { FileStatus, FileType, KnowledgeFile, KnowledgeSpace, SortDirection, SortType, SpaceRole, batchDeleteApi, batchDownloadApi, batchRetryApi, getFilePreviewApi } from "~/api/knowledge";
import { useConfirm, useToastContext } from "~/Providers";
import { useFileDragDrop } from "../hooks/useFileDragDrop";
import { ALLOWED_EXTENSIONS, DEFAULT_MAX_FILE_SIZE_MB, triggerUrlDownload } from "../knowledgeUtils";
import { bishengConfState } from "~/pages/appChat/store/atoms";
import { SearchParams } from "./CompoundSearchInput";
import { EditTagsModal } from "./EditTagsModal";
import { FileCard } from "./FileCard";
import { FileTable } from "./FileTable";
import { KnowledgeSpaceHeader } from "./KnowledgeSpaceHeader";
import { KnowledgeSpaceShareDialog } from "./KnowledgeSpaceShareDialog";
import { PaginationBar } from "./PaginationBar";
import { SelectionPathBreadcrumb } from "./SelectionPathBreadcrumb";
import { canOpenPermissionDialog, checkPermission } from "~/api/permission";
import {
    hasKnowledgeSpacePermission,
    useKnowledgeSpaceActionPermissions,
} from "../hooks/useKnowledgeSpacePermissions";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { cn, getFullWidthLength } from "~/utils";

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
    onSort: (sortBy: SortType | undefined, direction: SortDirection | undefined) => void;
    onNavigateFolder: (folderId?: string) => void;
    onUploadFile: (files?: FileList | File[]) => void;
    onCreateFolder: () => void;
    onDownloadFile: (fileId: string) => void;
    onRenameFile: (fileId: string, newName: string) => void;
    onDeleteFile: (fileId: string) => void;
    onEditTags: (fileId: string) => void;
    onRetryFile: (fileId: string) => void;
    currentPath: Array<{ id?: string; name: string }>;
    currentFolderId?: string;
    onDragStateChange?: (isDragging: boolean, error?: string | null) => void;
    uploadingFiles?: KnowledgeFile[];
    creatingFolder?: KnowledgeFile | null;
    onCancelCreateFolder?: () => void;
    onToggleAiAssistant?: () => void;
    isAiAssistantOpen?: boolean;
    onCreateSpace?: () => void;
    onGoKnowledgeSquare?: () => void;
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
    currentFolderId,
    onDragStateChange,
    uploadingFiles = [],
    creatingFolder,
    onCancelCreateFolder,
    onToggleAiAssistant,
    isAiAssistantOpen,
    onCreateSpace,
    onGoKnowledgeSquare,
}: KnowledgeSpaceContentProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
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
    const [sortBy, setSortBy] = useState<SortType | undefined>(undefined);
    const [sortDirection, setSortDirection] = useState<SortDirection | undefined>(undefined);
    const [editingTagsFileId, setEditingTagsFileId] = useState<string | null>(null);
    const [isBatchTagging, setIsBatchTagging] = useState(false);

    // Card view: compute columns by *container width* (not viewport width).
    // Thresholds (container width):
    // >=1296: 6, 1024-1295: 5, 768-1023: 4, 600-767: 3, 480-599: 2, <480: 1
    const cardGridRef = useRef<HTMLDivElement | null>(null);
    const calcCols = (w: number) => {
        if (w >= 1296) return 6;
        if (w >= 1024) return 5;
        if (w >= 768) return 4;
        if (w >= 600) return 3;
        if (w >= 480) return 2;
        return 1;
    };
    const [cardCols, setCardCols] = useState(() => {
        // Avoid first-paint "1 column" flash: start from viewport width, then refine with container width.
        const w = typeof window !== "undefined"
            ? (document.documentElement?.clientWidth || window.innerWidth || 0)
            : 0;
        return calcCols(w);
    });
    useLayoutEffect(() => {
        if (viewMode !== "card") return;
        const el = cardGridRef.current;
        if (!el) return;

        // Prefer the scroll container width (grid's parent) to avoid 0-width reads on first paint.
        const parent = el.parentElement as HTMLElement | null;
        const getWidth = () => parent?.clientWidth || el.clientWidth || 0;

        let rafId: number | null = null;
        const apply = () => {
            const w = getWidth();
            if (!w) {
                rafId = window.requestAnimationFrame(apply);
                return;
            }
            const cols = calcCols(w);
            setCardCols((prev) => (prev === cols ? prev : cols));
        };

        apply();
        const ro = new ResizeObserver(() => apply());
        ro.observe(el);
        if (parent) ro.observe(parent);
        return () => {
            if (rafId) window.cancelAnimationFrame(rafId);
            ro.disconnect();
        };
    }, [viewMode]);

    useEffect(() => {
        setSelectedFiles(new Set());
        setSearchQuery("");
        setSearchTagIds([]); // 切换空间时清空搜索条件
    }, [space.id]);

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    const { permissions: spaceActionPermissions } = useKnowledgeSpaceActionPermissions([space.id]);
    const canShareSpace = isAdmin || hasKnowledgeSpacePermission(
        spaceActionPermissions,
        space.id,
        "share_space",
    );
    const [canCreateFolder, setCanCreateFolder] = useState(false);
    const [canUploadFile, setCanUploadFile] = useState(false);
    const isSearching = searchQuery.trim().length > 0 || searchTagIds.length > 0;
    const [permTarget, setPermTarget] = useState<{
        id: string;
        name: string;
        type: "folder" | "knowledge_file";
    } | null>(null);
    const [permissionEntryIds, setPermissionEntryIds] = useState<Set<string>>(new Set());
    const [renameFolderEntryIds, setRenameFolderEntryIds] = useState<Set<string>>(new Set());
    const [deleteFolderEntryIds, setDeleteFolderEntryIds] = useState<Set<string>>(new Set());
    const permissionEntryProbeKey = displayFiles
        .filter((file) => !file.isCreating && /^\d+$/.test(String(file.id)))
        .map((file) => `${file.id}:${file.type}`)
        .join("|");

    const { showToast } = useToastContext();
    const confirm = useConfirm();

    useEffect(() => {
        let cancelled = false;
        const controller = new AbortController();

        const objectType = currentFolderId ? "folder" : "knowledge_space";
        const objectId = currentFolderId || space.id;

        Promise.allSettled([
            checkPermission(
                objectType,
                objectId,
                "can_edit",
                "create_folder",
                { signal: controller.signal },
            ),
            checkPermission(
                objectType,
                objectId,
                "can_edit",
                "upload_file",
                { signal: controller.signal },
            ),
        ]).then(([createFolderResult, uploadFileResult]) => {
            if (cancelled) return;
            setCanCreateFolder(
                createFolderResult.status === "fulfilled" && Boolean(createFolderResult.value?.allowed)
            );
            setCanUploadFile(
                uploadFileResult.status === "fulfilled" && Boolean(uploadFileResult.value?.allowed)
            );
        }).catch(() => {
            if (!cancelled) {
                setCanCreateFolder(false);
                setCanUploadFile(false);
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [currentFolderId, space.id]);

    useEffect(() => {
        let cancelled = false;
        const controller = new AbortController();
        const candidates = displayFiles.filter(
            (file) => !file.isCreating && /^\d+$/.test(String(file.id))
        );

        if (isAdmin) {
            setPermissionEntryIds(new Set(candidates.map((file) => file.id)));
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

        if (candidates.length === 0) {
            setPermissionEntryIds(new Set());
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

        Promise.all(
            candidates.map(async (file) => {
                const resourceType = file.type === FileType.FOLDER ? "folder" : "knowledge_file";
                const allowed = await canOpenPermissionDialog(resourceType, file.id, {
                    signal: controller.signal,
                }).catch(() => false);
                return allowed ? file.id : null;
            })
        ).then((ids) => {
            if (!cancelled) {
                setPermissionEntryIds(new Set(ids.filter((id): id is string => Boolean(id))));
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [
        isAdmin,
        permissionEntryProbeKey,
    ]);

    useEffect(() => {
        let cancelled = false;
        const controller = new AbortController();
        const folders = displayFiles.filter(
            (file) => file.type === FileType.FOLDER && !file.isCreating && /^\d+$/.test(String(file.id))
        );

        if (folders.length === 0) {
            setRenameFolderEntryIds(new Set());
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

        Promise.all(
            folders.map(async (file) => {
                const result = await checkPermission(
                    "folder",
                    file.id,
                    "can_edit",
                    "rename_folder",
                    { signal: controller.signal },
                ).catch(() => ({ allowed: false }));
                return result.allowed ? file.id : null;
            })
        ).then((ids) => {
            if (!cancelled) {
                setRenameFolderEntryIds(new Set(ids.filter((id): id is string => Boolean(id))));
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [permissionEntryProbeKey]);

    useEffect(() => {
        let cancelled = false;
        const controller = new AbortController();
        const folders = displayFiles.filter(
            (file) => file.type === FileType.FOLDER && !file.isCreating && /^\d+$/.test(String(file.id))
        );

        if (folders.length === 0) {
            setDeleteFolderEntryIds(new Set());
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

        Promise.all(
            folders.map(async (file) => {
                const result = await checkPermission(
                    "folder",
                    file.id,
                    "can_delete",
                    "delete_folder",
                    { signal: controller.signal },
                ).catch(() => ({ allowed: false }));
                return result.allowed ? file.id : null;
            })
        ).then((ids) => {
            if (!cancelled) {
                setDeleteFolderEntryIds(new Set(ids.filter((id): id is string => Boolean(id))));
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [permissionEntryProbeKey]);

    // Read max file size from env config (MB), fallback to default 200MB
    const bishengConfig = useRecoilValue(bishengConfState);
    const maxFileSizeMB = bishengConfig?.uploaded_files_maximum_size ?? DEFAULT_MAX_FILE_SIZE_MB;
    const maxFileSizeBytes = maxFileSizeMB * 1024 * 1024;

    // ─── File Upload Trigger ─────────────────────────────────────────────
    const fileInputRef = useRef<HTMLInputElement>(null);

    const triggerUpload = () => {
        if (!canUploadFile) return;
        fileInputRef.current?.click();
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
            const filesList = Array.from(e.target.files);

            if (filesList.length > 50) {
                showToast({ message: localize("com_knowledge.max_upload_50"), status: "error" });
                if (fileInputRef.current) fileInputRef.current.value = "";
                return;
            }

            for (let f of filesList) {
                if (f.size > maxFileSizeBytes) {
                    showToast({ message: localize("com_knowledge.file_exceeds_limit", { name: f.name, size: maxFileSizeMB }), status: "error" });
                    if (fileInputRef.current) fileInputRef.current.value = "";
                    return;
                }
                const ext = f.name.split('.').pop()?.toLowerCase();
                if (!ext || !(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
                    showToast({ message: localize("com_knowledge.unsupported_file_format", { 0: f.name }), status: "error" });
                    if (fileInputRef.current) fileInputRef.current.value = "";
                    return;
                }
            }

            if (canUploadFile) {
                onUploadFile(filesList);
            }
            if (fileInputRef.current) fileInputRef.current.value = "";
        }
    };

    // ─── Drag and drop ──────────────────────────────────────────────────
    const { handleDragEnter, handleDragLeave, handleDragOver, handleDrop } = useFileDragDrop({
        onDragStateChange,
        onUploadFile: canUploadFile ? onUploadFile : () => undefined,
        maxFileSizeMB,
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

    const handleManagePermission = (fileId: string) => {
        const target = displayFiles.find((file) => file.id === fileId);
        if (!target) {
            return;
        }

        setPermTarget({
            id: target.id,
            name: target.name,
            type: target.type === FileType.FOLDER ? "folder" : "knowledge_file",
        });
    };

    const handleSelectAll = (isAllSelectedOnPage: boolean) => {
        const newSelected = new Set(selectedFiles);
        if (isAllSelectedOnPage) {
            displayFiles.forEach(f => newSelected.delete(f.id));
        } else {
            displayFiles.forEach(f => newSelected.add(f.id));
        }
        setSelectedFiles(newSelected);
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
            if (!url) { showToast({ message: localize("com_knowledge.get_download_link_failed"), status: "error" }); return; }
            const now = new Date();
            const dateStr =
                String(now.getFullYear()) +
                String(now.getMonth() + 1).padStart(2, '0') +
                String(now.getDate()).padStart(2, '0');
            const randomStr = Math.random().toString(36).substring(2, 8).toUpperCase();
            triggerUrlDownload(url, `${dateStr}_${randomStr}.zip`);
        } catch {
            showToast({ message: localize("com_knowledge.download_failed"), status: "error" });
        }
    };

    const handleBatchTag = () => {
        setIsBatchTagging(true);
    };

    const handleSingleDownload = async (fileId: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        const isFolder = file?.type === FileType.FOLDER;
        try {
            if (isFolder) {
                // Folders must use batch download (returns zip)
                const url = await batchDownloadApi(space.id, {
                    folder_ids: [Number(fileId)],
                });
                if (!url) { showToast({ message: localize("com_knowledge.get_download_link_failed"), status: "error" }); return; }
                triggerUrlDownload(url, `${file?.name ?? "folder"}.zip`);
            } else {
                // Single file: use preview_url for channel files, original_url for others
                const previewData = await getFilePreviewApi(String(space.id), fileId);
                const downloadUrl = file?.fileSource === 'channel'
                    ? previewData.preview_url || previewData.original_url
                    : previewData.original_url;
                if (!downloadUrl) { showToast({ message: localize("com_knowledge.get_download_link_failed"), status: "error" }); return; }
                triggerUrlDownload(downloadUrl, file?.name);
            }
        } catch {
            showToast({ message: localize("com_knowledge.download_failed"), status: "error" });
        }
    };

    const handlePreviewFile = (fileId: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        const fileName = file?.name || localize("com_knowledge.unknown_file");
        // Use extension from filename for preview viewer dispatch instead of API type field
        const ext = fileName.split('.').pop()?.toLowerCase() || "";
        const url = `${__APP_ENV__.BASE_URL}/knowledge/file/${fileId}?name=${encodeURIComponent(fileName)}&type=${encodeURIComponent(ext)}&spaceId=${encodeURIComponent(space.id)}`;
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
            description: localize("com_knowledge.unsaved_tags_confirm_close"),
            cancelText: localize("com_knowledge.cancel"),
            confirmText: localize("com_knowledge.confirm_close")
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
            title: localize("com_knowledge.confirm_delete_selected_items", { 0: selectedFiles.size }),
            description: localize("com_knowledge.delete_folder_warning"),
            cancelText: localize("com_knowledge.cancel"),
            confirmText: localize("com_knowledge.delete"),
            variant: "destructive"
        });

        if (!confirmed) return;

        if (!canBatchDelete) {
            showToast({ message: localize("com_knowledge.batch_delete_failed"), status: "error" });
            return;
        }

        const fileIds = selectedList.filter(f => f.type !== FileType.FOLDER).map(f => Number(f.id));
        const folderIds = selectedList.filter(f => f.type === FileType.FOLDER).map(f => Number(f.id));

        try {
            await batchDeleteApi(space.id, {
                file_ids: fileIds.length ? fileIds : undefined,
                folder_ids: folderIds.length ? folderIds : undefined,
            });
            setSelectedFiles(new Set());
            showToast({ message: localize("com_knowledge.batch_delete_success"), status: "success" });
            // Notify parent to refresh the list
            onDeleteFile("");
        } catch {
            showToast({ message: localize("com_knowledge.batch_delete_failed"), status: "error" });
        }
    };

    const handleDelete = async (fileId: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        if (!file) return;

        const isFolder = file.type === FileType.FOLDER;

        const confirmed = await confirm({
            title: isFolder ? `确认删除文件夹 "${file.name}" 吗？` : localize("com_knowledge.confirm_delete_file"),
            description: isFolder ? localize("com_knowledge.delete_folder_permanent_warning") : undefined,
            cancelText: localize("com_knowledge.cancel"),
            confirmText: localize("com_knowledge.delete"),
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
            showToast({ message: localize("com_knowledge.batch_retry_started"), status: "success" });
            setSelectedFiles(new Set());
            // Refresh list
            onDeleteFile("");
        } catch {
            showToast({ message: localize("com_knowledge.batch_retry_failed"), status: "error" });
        }
    };

    const handleSingleRetry = async (fileId: string) => {
        try {
            await batchRetryApi(space.id, [Number(fileId)]);
            showToast({ message: localize("com_knowledge.retry_started"), status: "success" });
            // Refresh list
            onDeleteFile("");
        } catch {
            showToast({ message: localize("com_knowledge.retry_failed"), status: "error" });
        }
    };

    const validateFileName = (name: string, isFolder: boolean, currentId: string, isCreating: boolean) => {
        const trimmed = name.trim();
        if (!trimmed) {
            return isFolder && isCreating ? localize("com_knowledge.folder_name_empty") : localize("com_knowledge.name_empty");
        }
        if (getFullWidthLength(trimmed) > 50) {
            return localize("com_knowledge.name_max_50");
        }

        const duplicate = displayFiles.some(f => f.name === trimmed && f.id !== currentId && (isFolder ? f.type === FileType.FOLDER : f.type !== FileType.FOLDER));
        if (duplicate) {
            return isFolder ? localize("com_knowledge.name_duplicate_folder") : localize("com_knowledge.name_duplicate_file");
        }
        return null;
    };

    const hasFailedFiles = displayFiles.some(f =>
        selectedFiles.has(f.id) && (
            f.status === FileStatus.FAILED ||
            (f.type === FileType.FOLDER && f.successFileNum! < f.fileNum!)
        )
    );
    const hasFoldersSelected = displayFiles.some(f => selectedFiles.has(f.id) && f.type === FileType.FOLDER);
    const selectedList = displayFiles.filter(f => selectedFiles.has(f.id));
    const canBatchDelete = selectedList.length > 0 && selectedList.every((file) =>
        file.type === FileType.FOLDER ? deleteFolderEntryIds.has(file.id) : isAdmin
    );

    return (
        <div
            className="flex h-full min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-hidden rounded-lg px-4 touch-mobile:h-auto touch-mobile:min-h-full touch-mobile:overflow-y-auto"
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
        >
            {/* Hidden File Input */}
            <input
                type="file"
                multiple
                className="hidden"
                ref={fileInputRef}
                onChange={handleFileChange}
                accept={ALLOWED_EXTENSIONS.map(ext => `.${ext}`).join(',')}
            />
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
                enableCardMode
                statusFilter={statusFilter}
                onFilterStatus={handleStatusFilter}
                sortBy={sortBy}
                sortDirection={sortDirection}
                onSort={handleSort}
                onCreateFolder={onCreateFolder}
                onTriggerUpload={triggerUpload}
                canCreateFolder={canCreateFolder}
                canUploadFile={canUploadFile}
                selectedCount={selectedFiles.size}
                hasFoldersSelected={hasFoldersSelected}
                hasFailedFiles={hasFailedFiles}
                onClearSelection={() => setSelectedFiles(new Set())}
                onBatchDownload={handleBatchDownload}
                onBatchTag={handleBatchTag}
                onBatchRetry={handleBatchRetry}
                onBatchDelete={handleBatchDelete}
                canBatchDelete={canBatchDelete}
                onGoKnowledgeSquare={onGoKnowledgeSquare}
                onToggleAiAssistant={onToggleAiAssistant}
                isAiAssistantOpen={isAiAssistantOpen}
                canShareSpace={canShareSpace}
            />

            {/* Content Container (Scrollable) */}
            <div className="flex min-h-0 min-w-0 flex-1 flex-col touch-mobile:flex-none">
                <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-white touch-mobile:flex-none touch-mobile:overflow-visible">
                    {displayFiles.length === 0 ? (
                        <div className="flex h-full flex-1 flex-col items-center justify-center py-10 text-center">
                            <img
                                className="size-[120px] mb-4 object-contain opacity-90"
                                src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                alt="empty"
                            />
                            <p className="text-[14px] leading-6 text-[#4E5969]">
                                {searchQuery ? localize("com_knowledge.no_matched_file") : canUploadFile ? localize("com_knowledge.no_file_here_please") : localize("com_knowledge.no_file_here")}
                                {canUploadFile && !searchQuery && (
                                    <span
                                        className="cursor-pointer text-[#165DFF] transition-colors hover:text-[#4080FF] active:text-[#0E42D2]"
                                        onClick={triggerUpload}
                                    >
                                        {localize("com_knowledge.upload_file")}
                                    </span>
                                )}
                            </p>
                        </div>
                    ) : (isH5 || viewMode === "card") ? (
                        <div className="flex-1 overflow-y-auto scrollbar-on-hover touch-mobile:flex-none touch-mobile:overflow-visible">
                            <div
                                ref={cardGridRef}
                                className={cn(
                                    "w-full min-w-0 py-4",
                                    isH5
                                        ? viewMode === "list"
                                            ? "grid grid-cols-1 gap-2"
                                            : "grid grid-cols-2 gap-3"
                                        : "grid gap-4"
                                )}
                                style={
                                    isH5
                                        ? undefined
                                        : { gridTemplateColumns: `repeat(${cardCols}, minmax(0, 1fr))` }
                                }
                            >
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
                                    onManagePermission={permissionEntryIds.has(file.id) ? () => handleManagePermission(file.id) : undefined}
                                    canRename={file.type === FileType.FOLDER && renameFolderEntryIds.has(file.id)}
                                    canDelete={file.type === FileType.FOLDER ? deleteFolderEntryIds.has(file.id) : isAdmin}
                                    mobileListMode={isH5 && viewMode === "list"}
                                />
                            ))}
                            </div>
                        </div>
                    ) : (
                        <div className="flex min-h-0 min-w-0 flex-1 flex-col pb-4 touch-mobile:flex-none">
                            <div className="min-h-0 min-w-0 flex-1 overflow-y-auto scrollbar-on-hover border-t border-[#e5e6eb] touch-mobile:flex-none touch-mobile:overflow-visible">
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
                                    permissionEntryIds={permissionEntryIds}
                                    renameEntryIds={renameFolderEntryIds}
                                    deleteEntryIds={deleteFolderEntryIds}
                                    onManagePermission={handleManagePermission}
                                    sortBy={sortBy}
                                    sortDirection={sortDirection}
                                    onSort={handleSort}
                                />
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Footer */}
            <div className="flex flex-shrink-0 flex-wrap items-center justify-between gap-y-1 border-t border-[#e5e6eb] bg-white px-4 py-3 touch-mobile:mb-3">
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

            {permTarget && (
                <KnowledgeSpaceShareDialog
                    open={!!permTarget}
                    onOpenChange={(open) => {
                        if (!open) {
                            setPermTarget(null);
                        }
                    }}
                    resourceType={permTarget.type}
                    resourceId={permTarget.id}
                    resourceName={permTarget.name}
                    currentUserRole={space.role}
                    showShareTab={false}
                    showMembersTab={false}
                    showPermissionTab
                />
            )}
        </div>
    );
}
