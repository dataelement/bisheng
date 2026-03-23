import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
    FileStatus,
    FileType,
    KnowledgeFile,
    KnowledgeSpace,
    SortDirection,
    SortType,
    VisibilityType,
    getSpaceChildrenApi,
    searchSpaceChildrenApi,
    fileStatusToNumber,
    getFolderParentPathApi,
    getSpaceInfoApi,
    createSpaceApi,
    updateSpaceApi,
    getSquareSpacesApi,
    subscribeSpaceApi,
    createFolderApi,
    renameFolderApi,
    deleteFolderApi,
    uploadFileToServerApi,
    addFilesApi,
    renameFileApi,
    deleteFileApi,
} from "~/api/knowledge";
import { SearchParams } from "./SpaceDetail/CompoundSearchInput";
import { NotificationSeverity } from "~/common";
import { KnowledgeSpaceMemberDialog } from "~/components/KnowledgeSpaceMemberDialog";
import { useToastContext } from "~/Providers";
import { CreateKnowledgeSpaceDrawer, type CreateKnowledgeSpaceFormData } from "./CreateKnowledgeSpaceDrawer";
import { KnowledgeSpaceSidebar } from "./sidebar/KnowledgeSpaceSidebar";
import { KnowledgeSpaceContent } from "./SpaceDetail";
import { KnowledgeAiPanel } from "./SpaceDetail/AiChat/KnowledgeAiPanel";
import { KnowledgeSpacePreviewDrawer } from "./KnowledgeSpacePreviewDrawer";
import KnowledgeSquare from "./KnowledgeSquare";

/** Derive FileType enum from a file extension */
function getFileType(name: string): FileType {
    const ext = name.split('.').pop()?.toLowerCase();
    switch (ext) {
        case 'pdf': return FileType.PDF;
        case 'doc': return FileType.DOC;
        case 'docx': return FileType.DOCX;
        case 'xls': return FileType.XLS;
        case 'xlsx': return FileType.XLSX;
        case 'ppt': return FileType.PPT;
        case 'pptx': return FileType.PPTX;
        case 'jpg': return FileType.JPG;
        case 'jpeg': return FileType.JPEG;
        case 'png': return FileType.PNG;
        default: return FileType.OTHER;
    }
}

export default function Knowledge() {
    const MAX_USER_SPACES = 30;
    const [activeSpace, setActiveSpace] = useState<KnowledgeSpace | null>(null);
    const [files, setFiles] = useState<KnowledgeFile[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize] = useState(20);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState("");
    const [searchTagIds, setSearchTagIds] = useState<number[]>([]);
    const [searchScope, setSearchScope] = useState<'current' | 'all'>('all');
    const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
    const [sortBy, setSortBy] = useState<SortType | undefined>(undefined);
    const [sortDirection, setSortDirection] = useState<SortDirection | undefined>(undefined);
    const [currentFolderId, setCurrentFolderId] = useState<string | undefined>();
    const [currentPath, setCurrentPath] = useState<Array<{ id?: string; name: string }>>([]);
    const [showCreateDrawer, setShowCreateDrawer] = useState(false);
    const [editingSpace, setEditingSpace] = useState<KnowledgeSpace | null>(null);
    const [showKnowledgeSquare, setShowKnowledgeSquare] = useState(false);
    const [memberDialogOpen, setMemberDialogOpen] = useState(false);
    const [memberDialogSpace, setMemberDialogSpace] = useState<KnowledgeSpace | null>(null);
    const [isDragging, setIsDragging] = useState(false);
    const [dragError, setDragError] = useState<string | null>(null);
    const [uploadingFiles, setUploadingFiles] = useState<KnowledgeFile[]>([]);
    const [creatingFolder, setCreatingFolder] = useState<KnowledgeFile | null>(null);
    const [showAiAssistant, setShowAiAssistant] = useState(false);
    const [aiSplitWidth, setAiSplitWidth] = useState<number>(() => {
        const saved = localStorage.getItem("knowledge-ai-split-ratio");
        return saved ? parseInt(saved, 10) : 0;
    });
    const [isResizingSplit, setIsResizingSplit] = useState(false);
    const splitContainerRef = useRef<HTMLDivElement>(null);
    const { showToast } = useToastContext();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const { spaceId: previewSpaceId } = useParams<{ spaceId?: string }>();
    const [previewDrawerOpen, setPreviewDrawerOpen] = useState(false);
    const [squarePreviewSpaceId, setSquarePreviewSpaceId] = useState<string | undefined>();
    const [squarePreviewDrawerOpen, setSquarePreviewDrawerOpen] = useState(false);

    // ─── Load file/folder list ──────────────────────────────────────────
    const loadFiles = async (page: number = 1) => {
        if (!activeSpace?.id) return;

        setLoading(true);
        try {
            const isSearching = searchQuery.trim().length > 0 || searchTagIds.length > 0;
            const fileStatusNums = statusFilter.length > 0
                ? statusFilter.map(fileStatusToNumber)
                : undefined;
            const res = isSearching
                ? await searchSpaceChildrenApi({
                    space_id: activeSpace.id,
                    parent_id: searchScope === 'all' ? undefined : currentFolderId,
                    page,
                    page_size: pageSize,
                    keyword: searchQuery || undefined,
                    tag_ids: searchTagIds.length > 0 ? searchTagIds : undefined,
                    order_field: sortBy || undefined,
                    order_sort: sortDirection || undefined,
                    file_status: fileStatusNums,
                })
                : await getSpaceChildrenApi({
                    space_id: activeSpace.id,
                    parent_id: currentFolderId,
                    page,
                    page_size: pageSize,
                    order_field: sortBy || undefined,
                    order_sort: sortDirection || undefined,
                    file_status: fileStatusNums,
                });
            setFiles(res.data);
            setTotal(res.total);
            setCurrentPage(page);
        } catch (err) {
            showToast({ message: "加载文件列表失败", severity: NotificationSeverity.ERROR });
        } finally {
            setLoading(false);
        }
    };

    // Open preview drawer when URL has a spaceId param
    useEffect(() => {
        if (previewSpaceId) {
            setPreviewDrawerOpen(true);
        }
    }, [previewSpaceId]);

    // Reload files whenever active space changes
    useEffect(() => {
        if (activeSpace) {
            setCurrentPage(1);
            setCurrentFolderId(undefined);
            setCurrentPath([]);
            setSearchQuery("");
            setStatusFilter([]);
            loadFiles(1);
        }
    }, [activeSpace?.id]);

    // Reload files when folder navigation or filters change
    useEffect(() => {
        if (activeSpace) {
            setCurrentPage(1);
            loadFiles(1);
        }
    }, [searchQuery, searchTagIds, searchScope, statusFilter, sortBy, sortDirection, currentFolderId]);

    // Handle search from CompoundSearchInput
    const handleSearch = useCallback((params: SearchParams) => {
        setSearchQuery(params.keyword);
        setSearchTagIds(params.tagIds);
        setSearchScope(params.scope);
    }, []);

    // ─── Space actions ──────────────────────────────────────────────────
    const handleSpaceSelect = async (space: KnowledgeSpace | null) => {
        if (!space) {
            setActiveSpace(null);
            return;
        }
        // Set list-level data immediately for fast UI switch
        setActiveSpace(space);
        // Then fetch full detail from info API
        try {
            const detail = await getSpaceInfoApi(space.id);
            // Preserve the role from the list API (which has user_role).
            // The /info endpoint may not return user_role, so mapSpace defaults to MEMBER.
            // Only update role if detail explicitly provides a non-MEMBER role.
            const mergedRole = detail.role !== SpaceRole.MEMBER ? detail.role : space.role;
            setActiveSpace(prev => prev?.id === space.id ? { ...space, ...detail, id: space.id, role: mergedRole } : prev);
        } catch {
            // Keep list-level data if info fetch fails
        }
    };

    const handleCreateSpace = () => {
        setEditingSpace(null);
        setShowCreateDrawer(true);
    };

    // Open space settings drawer — fetch detail first, then open
    const handleSpaceSettings = async (space: KnowledgeSpace) => {
        try {
            const detail = await getSpaceInfoApi(space.id);
            setEditingSpace({ ...space, ...detail, id: space.id });
        } catch {
            // Fallback to list-level data if detail fetch fails
            setEditingSpace(space);
        }
        setShowCreateDrawer(true);
    };

    const handleConfirmCreateSpace = async (form: CreateKnowledgeSpaceFormData) => {
        try {
            // Map joinPolicy → auth_type
            const auth_type = form.joinPolicy === "public" ? VisibilityType.PUBLIC : VisibilityType.PRIVATE;
            const is_released = form.publishToSquare === "yes";

            if (editingSpace) {
                // ── Edit mode ──
                const updated = await updateSpaceApi(editingSpace.id, {
                    name: form.name,
                    description: form.description,
                    auth_type,
                    is_released,
                });
                if (activeSpace?.id === updated.id) setActiveSpace(updated);
                queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
                showToast({ message: "空间已更新", severity: NotificationSeverity.SUCCESS });
            } else {
                // ── Create mode ──
                const newSpace = await createSpaceApi({
                    name: form.name,
                    description: form.description,
                    auth_type,
                    is_released,
                });
                setActiveSpace(newSpace);
                setCurrentPath([]);
                queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces", "mine"] });
                showToast({ message: "知识空间创建成功", severity: NotificationSeverity.SUCCESS });
            }
        } catch (err) {
            showToast({
                message: editingSpace ? "更新空间失败" : "创建知识空间失败",
                severity: NotificationSeverity.ERROR
            });
        }
    };


    // ─── Pagination ─────────────────────────────────────────────────────
    const handlePageChange = (page: number) => {
        loadFiles(page);
    };

    // ─── Folder navigation ───────────────────────────────────────────────
    const handleNavigateFolder = async (folderId?: string) => {
        if (!folderId || !activeSpace) {
            // Navigate back to root
            setCurrentFolderId(undefined);
            setCurrentPath([]);
            return;
        }

        setCurrentFolderId(folderId);

        // Check if clicking a breadcrumb item already in the path
        const existingIdx = currentPath.findIndex(p => p.id === folderId);
        if (existingIdx >= 0) {
            setCurrentPath(prev => prev.slice(0, existingIdx + 1));
            return;
        }

        // Fetch the full parent chain from API
        const folder = files.find(f => f.id === folderId);
        const currentFolder = { id: folderId, name: folder?.name || folderId };
        try {
            const parentPath = await getFolderParentPathApi(activeSpace.id, folderId);
            setCurrentPath([...parentPath, currentFolder]);
        } catch {
            // Fallback: append folder to current path
            setCurrentPath(prev => [...prev, currentFolder]);
        }
    };

    // ─── File upload (two-step: server upload → register) ────────────────
    const handleUploadFile = async (files?: FileList | File[]) => {
        if (!activeSpace || !files || files.length === 0) {
            showToast({ message: "上传文件功能开发中", severity: NotificationSeverity.INFO });
            return;
        }

        const fileArray = Array.from(files);

        // Create placeholder uploading entries for UI
        const placeholders: KnowledgeFile[] = fileArray.map(file => ({
            id: `upload_${Date.now()}_${Math.random().toString(36).substring(7)}`,
            name: file.name,
            type: getFileType(file.name),
            size: file.size,
            status: FileStatus.UPLOADING,
            tags: [],
            path: file.name,
            parentId: currentFolderId,
            spaceId: activeSpace.id,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
        }));
        setUploadingFiles(prev => [...placeholders, ...prev]);

        showToast({ message: `已开始处理 ${fileArray.length} 个文件`, severity: NotificationSeverity.SUCCESS });

        // Upload each file and collect server paths
        const uploadedPaths: string[] = [];
        for (const file of fileArray) {
            try {
                const res = await uploadFileToServerApi(activeSpace.id, file);
                uploadedPaths.push(res.file_path);
            } catch (err) {
                showToast({ message: `文件 ${file.name} 上传失败`, severity: NotificationSeverity.ERROR });
            }
        }

        // Remove all placeholder entries
        setUploadingFiles(prev =>
            prev.filter(f => !placeholders.some(p => p.id === f.id))
        );

        if (uploadedPaths.length === 0) return;

        // Register uploaded files into the space
        try {
            await addFilesApi(activeSpace.id, {
                file_path: uploadedPaths,
                parent_id: currentFolderId ? Number(currentFolderId) : null,
            });
            // Refresh the file list to reflect new entries
            loadFiles(currentPage);
        } catch (err) {
            console.log('err :>> ', err);
            showToast({ message: "文件注册到知识空间失败", severity: NotificationSeverity.ERROR });
        }
    };

    // ─── Folder CRUD ─────────────────────────────────────────────────────
    const handleCreateFolder = () => {
        if (currentPath.length >= 10) {
            showToast({ message: "已达文件夹层级上限 10 级", severity: NotificationSeverity.WARNING } as any);
            return;
        }

        const genRandomStr = () =>
            Math.random().toString(36).substring(2, 8).toUpperCase() +
            Math.random().toString(36).substring(2, 8).toUpperCase();
        const randomStr = genRandomStr().substring(0, 12);

        const newFolder: KnowledgeFile = {
            id: `temp_folder_${Date.now()}`,
            name: `未命名文件夹_${randomStr}`,
            type: FileType.FOLDER,
            tags: [],
            path: `未命名文件夹_${randomStr}`,
            parentId: currentFolderId,
            spaceId: activeSpace?.id || '',
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            status: FileStatus.SUCCESS,
            isCreating: true,
        } as any;

        setCreatingFolder(newFolder);
    };

    const handleCancelCreateFolder = () => {
        setCreatingFolder(null);
    };

    /** Called when the inline-rename input is confirmed (new name submitted) */
    const handleRenameFile = async (fileId: string, newName: string) => {
        if (!activeSpace) return;

        // ── Confirm in-progress folder creation ──
        if (creatingFolder && fileId === creatingFolder.id) {
            try {
                const created = await createFolderApi(activeSpace.id, {
                    name: newName,
                    parent_id: currentFolderId || null,
                });
                setFiles(prev => [created, ...prev]);
                setCreatingFolder(null);
                showToast({ message: "文件夹新建成功", severity: NotificationSeverity.SUCCESS } as any);
            } catch (err) {
                showToast({ message: "新建文件夹失败", severity: NotificationSeverity.ERROR });
            }
            return;
        }

        // ── Rename existing item ──
        const target = files.find(f => f.id === fileId);
        if (!target) return;

        try {
            if (target.type === FileType.FOLDER) {
                await renameFolderApi(activeSpace.id, fileId, newName);
            } else {
                await renameFileApi(activeSpace.id, fileId, newName);
            }
            setFiles(prev => prev.map(f => f.id === fileId ? { ...f, name: newName } : f));
            showToast({ message: "重命名成功", severity: NotificationSeverity.SUCCESS } as any);
        } catch (err) {
            showToast({ message: "重命名失败", severity: NotificationSeverity.ERROR });
        }
    };

    const handleDeleteFile = async (fileId: string) => {
        if (!activeSpace) return;

        // Empty fileId is used as a "batch delete done" signal — just refresh
        if (!fileId) {
            loadFiles(currentPage);
            return;
        }

        const target = files.find(f => f.id === fileId);
        if (!target) return;

        try {
            if (target.type === FileType.FOLDER) {
                await deleteFolderApi(activeSpace.id, fileId);
            } else {
                await deleteFileApi(activeSpace.id, fileId);
            }
            setFiles(prev => prev.filter(f => f.id !== fileId));
            showToast({ message: "已删除", severity: NotificationSeverity.SUCCESS });
        } catch (err) {
            showToast({ message: "删除失败", severity: NotificationSeverity.ERROR });
        }
    };

    const handleDownloadFile = (fileId: string) => {
        showToast({ message: "开始下载", severity: NotificationSeverity.SUCCESS });
    };

    const handleEditTags = (fileId: string) => {
        loadFiles(currentPage);
    };

    const handleRetryFile = (fileId: string) => {
        showToast({ message: "重试功能开发中", severity: NotificationSeverity.INFO });
    };

    const handleSort = (newSortBy: SortType, newDirection: SortDirection) => {
        setSortBy(newSortBy);
        setSortDirection(newDirection);
    };

    const handleKnowledgeSquare = () => {
        setShowKnowledgeSquare(true);
    };

    const handleDragStateChange = (dragging: boolean, error?: string | null) => {
        setIsDragging(dragging);
        setDragError(error || null);
    };

    // ─── AI Split-pane logic ─────────────────────────────────────────────
    const AI_MIN_LEFT = 480;
    const AI_MIN_RIGHT = 360;

    const handleToggleAiAssistant = useCallback(() => {
        setShowAiAssistant(prev => {
            if (!prev && splitContainerRef.current) {
                const containerWidth = splitContainerRef.current.getBoundingClientRect().width;
                if (containerWidth < AI_MIN_LEFT + AI_MIN_RIGHT) {
                    showToast({ message: "窗口宽度不足，无法打开 AI 助手", severity: NotificationSeverity.WARNING } as any);
                    return false;
                }
                if (!aiSplitWidth || aiSplitWidth <= 0) {
                    setAiSplitWidth(Math.floor(containerWidth * 0.6));
                }
            }
            return !prev;
        });
    }, [aiSplitWidth, showToast]);

    useEffect(() => {
        if (!showAiAssistant || !splitContainerRef.current) return;
        const el = splitContainerRef.current;
        const ro = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const w = entry.contentRect.width;
                if (w < AI_MIN_LEFT + AI_MIN_RIGHT) setShowAiAssistant(false);
                if (w - aiSplitWidth < AI_MIN_RIGHT) setAiSplitWidth(Math.max(AI_MIN_LEFT, w - AI_MIN_RIGHT));
            }
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, [showAiAssistant, aiSplitWidth]);

    const startSplitResize = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        setIsResizingSplit(true);
    }, []);

    const stopSplitResize = useCallback(() => {
        setIsResizingSplit(false);
        if (aiSplitWidth > 0) localStorage.setItem("knowledge-ai-split-ratio", aiSplitWidth.toString());
    }, [aiSplitWidth]);

    const resizeSplit = useCallback((e: MouseEvent) => {
        if (!isResizingSplit || !splitContainerRef.current) return;
        const rect = splitContainerRef.current.getBoundingClientRect();
        const newLeft = e.clientX - rect.left;
        if (newLeft >= AI_MIN_LEFT && (rect.width - newLeft) >= AI_MIN_RIGHT) setAiSplitWidth(newLeft);
    }, [isResizingSplit]);

    useEffect(() => {
        if (isResizingSplit) {
            window.addEventListener("mousemove", resizeSplit);
            window.addEventListener("mouseup", stopSplitResize);
        } else {
            window.removeEventListener("mousemove", resizeSplit);
            window.removeEventListener("mouseup", stopSplitResize);
        }
        return () => {
            window.removeEventListener("mousemove", resizeSplit);
            window.removeEventListener("mouseup", stopSplitResize);
        };
    }, [isResizingSplit, resizeSplit, stopSplitResize]);

    const locationKey = currentFolderId || activeSpace?.id || "";
    const contextLabel = currentFolderId ? "文件夹" : "知识空间";

    // Knowledge square view
    if (showKnowledgeSquare) {
        return (
            <div className="relative h-full flex">
                <KnowledgeSquare
                    onBack={() => setShowKnowledgeSquare(false)}
                    title="探索知识广场"
                    subtitle="您可以在这里探索更多的知识空间"
                    searchPlaceholder="输入知识空间名称或描述进行搜索"
                    emptyText="未找到匹配知识空间"
                    joinToastPrefix="已申请加入知识空间："
                    onPreviewSpace={(id) => {
                        setSquarePreviewSpaceId(id);
                        setSquarePreviewDrawerOpen(true);
                    }}
                />
                <KnowledgeSpacePreviewDrawer
                    spaceId={squarePreviewSpaceId}
                    open={squarePreviewDrawerOpen}
                    onOpenChange={(open) => {
                        setSquarePreviewDrawerOpen(open);
                        if (!open) setSquarePreviewSpaceId(undefined);
                    }}
                />
            </div>
        );
    }

    return (
        <div className="relative h-full flex">
            {/* Drag and Drop Overlay */}
            {isDragging && (
                <div className={`absolute inset-0.5 z-[100] rounded-[12px] bg-[rgba(255,255,255,0.7)] backdrop-blur-[16px] flex flex-col items-center justify-center pointer-events-none transition-all duration-300 ${dragError ? 'border border-dashed border-red-500' : 'border border-dashed'}`}>
                    <div className="flex flex-col items-center justify-center p-8 bg-white/50 rounded-2xl">
                        {dragError ? (
                            <p className="text-xl font-medium text-red-500 mb-2">{dragError}</p>
                        ) : (
                            <p className="text-xl font-medium text-[#161616] mb-2">松手即可上传文件至此处</p>
                        )}
                        <div className="text-center text-xs text-gray-400 leading-5">
                            <p>支持的文件格式为：</p>
                            <p>pdf(含扫描件)、txt、docx、ppt、pptx、md、html、xls、xlsx、csv、doc、png、jpg、jpeg、bmp</p>
                            <p>每个文件最大支持200mb</p>
                            <p>单次最多上传50个</p>
                        </div>
                    </div>
                </div>
            )}

            <KnowledgeSpaceSidebar
                activeSpaceId={activeSpace?.id}
                onSpaceSelect={handleSpaceSelect}
                onCreateSpace={handleCreateSpace}
                onSpaceSettings={handleSpaceSettings}
                onKnowledgeSquare={handleKnowledgeSquare}
            />

            {activeSpace ? (
                <div ref={splitContainerRef} className="flex-1 flex h-full overflow-hidden">
                    {/* Left: file list */}
                    <div
                        style={{ width: showAiAssistant ? `${aiSplitWidth}px` : '100%' }}
                        className="h-full flex-shrink-0 overflow-hidden"
                    >
                        <KnowledgeSpaceContent
                            space={activeSpace}
                            files={files}
                            currentPage={currentPage}
                            pageSize={pageSize}
                            total={total}
                            onPageChange={handlePageChange}
                            loading={loading}
                            onSearch={handleSearch}
                            onFilterStatus={setStatusFilter}
                            onSort={handleSort}
                            onNavigateFolder={handleNavigateFolder}
                            onUploadFile={handleUploadFile}
                            onCreateFolder={handleCreateFolder}
                            onDownloadFile={handleDownloadFile}
                            onRenameFile={handleRenameFile}
                            onDeleteFile={handleDeleteFile}
                            onEditTags={handleEditTags}
                            onRetryFile={handleRetryFile}
                            currentPath={currentPath}
                            onDragStateChange={handleDragStateChange}
                            uploadingFiles={uploadingFiles}
                            creatingFolder={creatingFolder}
                            onCancelCreateFolder={handleCancelCreateFolder}
                            onToggleAiAssistant={handleToggleAiAssistant}
                            isAiAssistantOpen={showAiAssistant}
                        />
                    </div>

                    {/* Splitter */}
                    {showAiAssistant && (
                        <div
                            onMouseDown={startSplitResize}
                            className="group relative w-[1px] cursor-col-resize bg-[#e5e6eb] transition-all hover:w-1 hover:bg-primary active:w-1 active:bg-primary z-20 shrink-0"
                        >
                            <div className="absolute inset-y-0 -left-1.5 -right-1.5 z-10" />
                        </div>
                    )}

                    {/* Right: AI assistant */}
                    {showAiAssistant && (
                        <div className="flex-1 h-full min-w-[360px] bg-white border-l border-[#e5e6eb]">
                            <KnowledgeAiPanel
                                spaceId={activeSpace.id}
                                folderId={currentFolderId}
                                locationKey={locationKey}
                                contextLabel={contextLabel}
                                availableTags={[]}
                                onClose={() => setShowAiAssistant(false)}
                            />
                        </div>
                    )}
                </div>
            ) : (
                /* Empty state when no space is selected */
                <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
                    <img
                        className="size-[120px] mb-4 object-contain opacity-90"
                        src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                        alt="empty"
                    />
                    <p className="text-[14px] leading-6 text-[#4E5969]">
                        无相关内容，请
                        <span
                            className="ml-1.5 cursor-pointer text-[#165DFF] transition-colors hover:text-[#4080FF] active:text-[#0E42D2]"
                            onClick={handleCreateSpace}
                        >
                            创建知识空间
                        </span>
                    </p>
                </div>
            )}

            <CreateKnowledgeSpaceDrawer
                open={showCreateDrawer}
                onOpenChange={setShowCreateDrawer}
                onConfirm={handleConfirmCreateSpace}
                mode={editingSpace ? "edit" : "create"}
                editingSpace={editingSpace}
                onViewSpace={() => setShowCreateDrawer(false)}
                onManageMembers={() => {
                    setShowCreateDrawer(false);
                    setMemberDialogSpace(activeSpace);
                    setMemberDialogOpen(true);
                }}
            />

            <KnowledgeSpaceMemberDialog
                open={memberDialogOpen}
                onOpenChange={setMemberDialogOpen}
                space={memberDialogSpace}
            />

            <KnowledgeSpacePreviewDrawer
                spaceId={previewSpaceId}
                open={previewDrawerOpen}
                onOpenChange={(open) => {
                    setPreviewDrawerOpen(open);
                    if (!open) navigate("/knowledge", { replace: true });
                }}
            />
        </div>
    );
}
