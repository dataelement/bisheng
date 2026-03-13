import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { FileStatus, FileType, KnowledgeFile, KnowledgeSpace, SortDirection, SortType, SpaceRole, VisibilityType } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { KnowledgeSpaceMemberDialog } from "~/components/KnowledgeSpaceMemberDialog";
import { getMockFiles, getMockKnowledgeSpaces, getMockTags } from "~/mock/knowledge";
import { useToastContext } from "~/Providers";
import ChannelSquare from "../ChannelSquare";
import { CreateKnowledgeSpaceDrawer, type CreateKnowledgeSpaceFormData } from "./CreateKnowledgeSpaceDrawer";
import { KnowledgeSpaceSidebar } from "./sidebar/KnowledgeSpaceSidebar";
import { KnowledgeSpaceContent } from "./SpaceDetail";
import { KnowledgeAiPanel } from "./SpaceDetail/AiChat/KnowledgeAiPanel";
import { KnowledgeSpacePreviewDrawer } from "./KnowledgeSpacePreviewDrawer";

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
    const [createdSpaces, setCreatedSpaces] = useState<KnowledgeSpace[]>([]);
    const [joinedSpaces, setJoinedSpaces] = useState<KnowledgeSpace[]>([]);
    const [activeSpace, setActiveSpace] = useState<KnowledgeSpace | null>(null);
    const [files, setFiles] = useState<KnowledgeFile[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(20);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState("");
    const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
    const [sortBy, setSortBy] = useState(SortType.UPDATE_TIME);
    const [sortDirection, setSortDirection] = useState(SortDirection.DESC);
    const [currentFolderId, setCurrentFolderId] = useState<string | undefined>();
    const [currentPath, setCurrentPath] = useState<Array<{ id?: string; name: string }>>([]);
    const [showCreateDrawer, setShowCreateDrawer] = useState(false);
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
        return saved ? parseInt(saved, 10) : 0; // 0 means "use default on first open"
    });
    const [isResizingSplit, setIsResizingSplit] = useState(false);
    const splitContainerRef = useRef<HTMLDivElement>(null);
    const { showToast } = useToastContext();
    const navigate = useNavigate();
    const { spaceId: previewSpaceId } = useParams<{ spaceId?: string }>();
    const [previewDrawerOpen, setPreviewDrawerOpen] = useState(false);

    // 加载知识空间列表
    const loadSpaces = () => {
        const created = getMockKnowledgeSpaces("created");
        const joined = getMockKnowledgeSpaces("joined");

        setCreatedSpaces(created);
        setJoinedSpaces(joined);

        // 默认选中第一个空间
        if (!activeSpace && created.length > 0) {
            setActiveSpace(created[0]);
            setCurrentPath([{ id: '1', name: created[0].name + 1 }]);
        }
    };

    // 加载文件列表
    const loadFiles = (page: number = 1) => {
        if (!activeSpace) return;

        setLoading(true);
        setTimeout(() => {
            const response = getMockFiles({
                spaceId: activeSpace.id,
                parentId: currentFolderId,
                search: searchQuery,
                statusFilter: statusFilter.length > 0 ? statusFilter : undefined,
                page,
                pageSize: 20
            });

            setFiles(response.data);
            setTotal(response.total);
            setCurrentPage(page);
            setLoading(false);
        }, 300);
    };

    // 初始加载
    useEffect(() => {
        loadSpaces();
    }, []);

    // 打开分享预览抽屉
    useEffect(() => {
        if (previewSpaceId) {
            setPreviewDrawerOpen(true);
        }
    }, [previewSpaceId]);

    // 空间切换时重新加载文件
    useEffect(() => {
        if (activeSpace) {
            setCurrentPage(1);
            setCurrentFolderId(undefined);
            setCurrentPath([{ id: '1', name: activeSpace.name }, { id: '2', name: '测试' }]);
            setSearchQuery("");
            setStatusFilter([]);
            loadFiles(1);
        }
    }, [activeSpace]);

    // 筛选条件变化时重新加载
    useEffect(() => {
        if (activeSpace) {
            setCurrentPage(1);
            loadFiles(1);
        }
    }, [searchQuery, statusFilter, sortBy, sortDirection, currentFolderId]);

    // 处理空间选择
    const handleSpaceSelect = (space: KnowledgeSpace) => {
        setActiveSpace(space);
    };

    // 创建空间
    const handleCreateSpace = () => {
        if (createdSpaces.length >= MAX_USER_SPACES) {
            showToast({
                message: "您已达到创建知识空间的上限",
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        setShowCreateDrawer(true);
    };

    const handleConfirmCreateSpace = (form: CreateKnowledgeSpaceFormData) => {
        const now = new Date().toISOString();
        const newSpace: KnowledgeSpace = {
            id: `space-${Date.now()}`,
            name: form.name,
            description: form.description,
            visibility: form.joinPolicy === "private" ? VisibilityType.PRIVATE : VisibilityType.PUBLIC,
            creator: "当前用户",
            creatorId: "current-user",
            memberCount: 1,
            fileCount: 0,
            totalFileCount: 0,
            role: SpaceRole.CREATOR,
            isPinned: false,
            createdAt: now,
            updatedAt: now,
            tags: []
        };
        setCreatedSpaces((prev) => [newSpace, ...prev]);
        setActiveSpace(newSpace);
        setCurrentPath([{ name: newSpace.name }]);
        showToast({
            message: "知识空间创建成功",
            severity: NotificationSeverity.SUCCESS
        });
    };

    // 更新空间
    const handleUpdateSpace = (space: KnowledgeSpace) => {
        setCreatedSpaces(prev =>
            prev.map(s => s.id === space.id ? space : s)
        );
        setJoinedSpaces(prev =>
            prev.map(s => s.id === space.id ? space : s)
        );

        if (activeSpace?.id === space.id) {
            setActiveSpace(space);
        }

        showToast({
            message: "空间已更新",
            severity: NotificationSeverity.SUCCESS
        });
    };

    // 删除空间
    const handleDeleteSpace = (spaceId: string) => {
        setCreatedSpaces(prev => prev.filter(s => s.id !== spaceId));

        if (activeSpace?.id === spaceId) {
            setActiveSpace(createdSpaces[0] || joinedSpaces[0] || null);
        }

        showToast({
            message: "空间已解散",
            severity: NotificationSeverity.SUCCESS
        });
    };

    // 退出空间
    const handleLeaveSpace = (spaceId: string) => {
        setJoinedSpaces(prev => prev.filter(s => s.id !== spaceId));

        if (activeSpace?.id === spaceId) {
            setActiveSpace(createdSpaces[0] || joinedSpaces[0] || null);
        }

        showToast({
            message: "已退出空间",
            severity: NotificationSeverity.SUCCESS
        });
    };

    // 置顶空间
    const handlePinSpace = (spaceId: string, pinned: boolean) => {
        const updateSpaces = (spaces: KnowledgeSpace[]) =>
            spaces.map(s =>
                s.id === spaceId ? { ...s, isPinned: pinned } : s
            );

        setCreatedSpaces(prev => updateSpaces(prev));
        setJoinedSpaces(prev => updateSpaces(prev));

        if (activeSpace?.id === spaceId) {
            setActiveSpace(prev => prev ? { ...prev, isPinned: pinned } : null);
        }

        showToast({
            message: pinned ? "已置顶" : "已取消置顶",
            severity: NotificationSeverity.SUCCESS
        });
    };

    // 页码切换
    const handlePageChange = (page: number) => {
        loadFiles(page);
    };

    // 文件夹导航
    const handleNavigateFolder = (folderId?: string) => {
        setCurrentFolderId(folderId);
        // TODO: Update currentPath based on folder navigation
    };

    // 文件操作
    const handleUploadFile = (files?: FileList | File[]) => {
        if (files && files.length > 0) {
            console.log("Uploading files:", files);
            const newUploading = Array.from(files).map(file => ({
                id: `upload_${Date.now()}_${Math.random().toString(36).substring(7)}`,
                name: file.name,
                type: getFileType(file.name),
                size: file.size,
                status: FileStatus.PROCESSING,
                tags: [],
                path: (currentPath.map(p => p.name).join('/') + '/' + file.name),
                parentId: currentFolderId,
                spaceId: activeSpace?.id || '',
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString(),
            }));

            // Add to uploadingFiles
            setUploadingFiles(prev => [...newUploading, ...prev]);

            showToast({
                message: `已开始处理 ${files.length} 个文件`,
                severity: NotificationSeverity.SUCCESS
            });
            return;
        }
        showToast({
            message: "上传文件功能开发中",
            severity: NotificationSeverity.INFO
        });
    };

    const handleCreateFolder = () => {
        if (currentPath.length >= 10) {
            showToast({
                message: "已达文件夹层级上限 10 级",
                severity: NotificationSeverity.WARNING
            } as any);
            return;
        }

        const genRandomStr = () => Math.random().toString(36).substring(2, 8).toUpperCase() + Math.random().toString(36).substring(2, 8).toUpperCase();
        const randomStr = genRandomStr().substring(0, 12);

        const newFolder: KnowledgeFile = {
            id: `temp_folder_${Date.now()}`,
            name: `未命名文件夹_${randomStr}`,
            type: FileType.FOLDER,
            tags: [],
            path: currentPath.map(p => p.name).join('/') + '/' + `未命名文件夹_${randomStr}`,
            parentId: currentFolderId,
            spaceId: activeSpace?.id || '',
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            status: FileStatus.SUCCESS,
            isCreating: true
        } as any;

        setCreatingFolder(newFolder);
    };

    const handleCancelCreateFolder = () => {
        setCreatingFolder(null);
    };

    const handleDownloadFile = (fileId: string) => {
        showToast({
            message: "开始下载",
            severity: NotificationSeverity.SUCCESS
        });
    };

    const handleRenameFile = (fileId: string, newName: string) => {
        if (creatingFolder && fileId === creatingFolder.id) {
            // Confirm creation
            showToast({
                message: `文件夹新建成功`,
                severity: NotificationSeverity.SUCCESS
            } as any);

            const newFile: KnowledgeFile = {
                ...creatingFolder,
                id: `new_folder_${Date.now()}`,
                name: newName,
            };
            delete (newFile as any).isCreating;

            setFiles(prev => [newFile, ...prev]);
            setCreatingFolder(null);
            return;
        }

        setFiles(prev => prev.map(f => f.id === fileId ? { ...f, name: newName } : f));
        showToast({
            message: "重命名成功",
            severity: NotificationSeverity.SUCCESS
        } as any);
    };

    const handleDeleteFile = (fileId: string) => {
        setFiles(prev => prev.filter(f => f.id !== fileId));
        showToast({
            message: "文件已删除",
            severity: NotificationSeverity.SUCCESS
        });
    };

    const handleEditTags = (fileId: string) => {
        showToast({
            message: "编辑标签功能开发中",
            severity: NotificationSeverity.INFO
        });
    };

    const handleRetryFile = (fileId: string) => {
        showToast({
            message: "重试中...",
            severity: NotificationSeverity.INFO
        });
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

    // --- AI Split-pane logic ---
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
                // Set default width if not previously saved
                if (!aiSplitWidth || aiSplitWidth <= 0) {
                    setAiSplitWidth(Math.floor(containerWidth * 0.6));
                }
            }
            return !prev;
        });
    }, [aiSplitWidth, showToast]);

    // ResizeObserver: auto-close AI panel when container is too narrow
    useEffect(() => {
        if (!showAiAssistant || !splitContainerRef.current) return;
        const el = splitContainerRef.current;
        const ro = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const w = entry.contentRect.width;
                if (w < AI_MIN_LEFT + AI_MIN_RIGHT) {
                    setShowAiAssistant(false);
                }
                // Clamp leftWidth if it exceeds available space
                if (w - aiSplitWidth < AI_MIN_RIGHT) {
                    setAiSplitWidth(Math.max(AI_MIN_LEFT, w - AI_MIN_RIGHT));
                }
            }
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, [showAiAssistant, aiSplitWidth]);

    // Splitter drag handlers
    const startSplitResize = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        setIsResizingSplit(true);
    }, []);

    const stopSplitResize = useCallback(() => {
        setIsResizingSplit(false);
        if (aiSplitWidth > 0) {
            localStorage.setItem("knowledge-ai-split-ratio", aiSplitWidth.toString());
        }
    }, [aiSplitWidth]);

    const resizeSplit = useCallback((e: MouseEvent) => {
        if (!isResizingSplit || !splitContainerRef.current) return;
        const rect = splitContainerRef.current.getBoundingClientRect();
        const newLeft = e.clientX - rect.left;
        // Clamp
        if (newLeft >= AI_MIN_LEFT && (rect.width - newLeft) >= AI_MIN_RIGHT) {
            setAiSplitWidth(newLeft);
        }
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

    // Compute locationKey and context label
    const locationKey = currentFolderId || activeSpace?.id || "";
    const contextLabel = currentFolderId ? "文件夹" : "知识空间";

    // 探索知识广场视图：全屏占位，行为与频道广场一致
    if (showKnowledgeSquare) {
        return (
            <div className="relative h-full flex">
                <ChannelSquare
                    onBack={() => setShowKnowledgeSquare(false)}
                    title="探索知识广场"
                    subtitle="您可以在这里探索更多的知识空间"
                    searchPlaceholder="输入知识空间名称或描述进行搜索"
                    emptyText="未找到匹配知识空间"
                    joinToastPrefix="已申请加入知识空间："
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
                createdSpaces={createdSpaces}
                joinedSpaces={joinedSpaces}
                activeSpaceId={activeSpace?.id}
                onSpaceSelect={handleSpaceSelect}
                onCreateSpace={handleCreateSpace}
                onUpdateSpace={handleUpdateSpace}
                onDeleteSpace={handleDeleteSpace}
                onLeaveSpace={handleLeaveSpace}
                onPinSpace={handlePinSpace}
                onKnowledgeSquare={handleKnowledgeSquare}
            />

            {activeSpace && (
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
                            onSearch={setSearchQuery}
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
                            {/* Expand click area */}
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
                                availableTags={getMockTags()}
                                onClose={() => setShowAiAssistant(false)}
                            />
                        </div>
                    )}
                </div>
            )}

            <CreateKnowledgeSpaceDrawer
                open={showCreateDrawer}
                onOpenChange={setShowCreateDrawer}
                onConfirm={handleConfirmCreateSpace}
                onViewSpace={() => {
                    setShowCreateDrawer(false);
                }}
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
                    if (!open) {
                        navigate("/knowledge", { replace: true });
                    }
                }}
            />
        </div>
    );
}
