import { useState, useEffect } from "react";
import { KnowledgeSpaceSidebar } from "./sidebar/KnowledgeSpaceSidebar";
import { KnowledgeSpaceContent } from "./SpaceDetail";
import { KnowledgeSpace, KnowledgeFile, FileStatus, SortType, SortDirection } from "~/api/knowledge";
import { getMockKnowledgeSpaces, getMockFiles } from "~/mock/knowledge";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";

export default function Knowledge() {
    const [createdSpaces, setCreatedSpaces] = useState<KnowledgeSpace[]>([]);
    const [joinedSpaces, setJoinedSpaces] = useState<KnowledgeSpace[]>([]);
    const [activeSpace, setActiveSpace] = useState<KnowledgeSpace | null>(null);
    const [files, setFiles] = useState<KnowledgeFile[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState("");
    const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
    const [sortBy, setSortBy] = useState(SortType.UPDATE_TIME);
    const [sortDirection, setSortDirection] = useState(SortDirection.DESC);
    const [currentFolderId, setCurrentFolderId] = useState<string | undefined>();
    const [currentPath, setCurrentPath] = useState<Array<{ id?: string; name: string }>>([]);
    const { showToast } = useToastContext();

    // 加载知识空间列表
    const loadSpaces = () => {
        const created = getMockKnowledgeSpaces("created");
        const joined = getMockKnowledgeSpaces("joined");

        setCreatedSpaces(created);
        setJoinedSpaces(joined);

        // 默认选中第一个空间
        if (!activeSpace && created.length > 0) {
            setActiveSpace(created[0]);
            setCurrentPath([{ name: created[0].name }]);
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

            if (page === 1) {
                setFiles(response.data);
            } else {
                setFiles(prev => [...prev, ...response.data]);
            }

            setHasMore(response.total > page * 20);
            setCurrentPage(page);
            setLoading(false);
        }, 300);
    };

    // 初始加载
    useEffect(() => {
        loadSpaces();
    }, []);

    // 空间切换时重新加载文件
    useEffect(() => {
        if (activeSpace) {
            setCurrentPage(1);
            setCurrentFolderId(undefined);
            setCurrentPath([{ name: activeSpace.name }]);
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
        showToast({
            message: "创建空间功能开发中",
            severity: NotificationSeverity.INFO
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

    // 加载更多文件
    const handleLoadMore = () => {
        loadFiles(currentPage + 1);
    };

    // 文件夹导航
    const handleNavigateFolder = (folderId?: string) => {
        setCurrentFolderId(folderId);
        // TODO: Update currentPath based on folder navigation
    };

    // 文件操作
    const handleUploadFile = () => {
        showToast({
            message: "上传文件功能开发中",
            severity: NotificationSeverity.INFO
        });
    };

    const handleCreateFolder = () => {
        showToast({
            message: "创建文件夹功能开发中",
            severity: NotificationSeverity.INFO
        });
    };

    const handleDownloadFile = (fileId: string) => {
        showToast({
            message: "开始下载",
            severity: NotificationSeverity.SUCCESS
        });
    };

    const handleRenameFile = (fileId: string) => {
        showToast({
            message: "重命名功能开发中",
            severity: NotificationSeverity.INFO
        });
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

    return (
        <div className="relative h-full flex">
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
            />

            {activeSpace ? (
                <KnowledgeSpaceContent
                    space={activeSpace}
                    files={files}
                    onLoadMore={handleLoadMore}
                    hasMore={hasMore}
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
                />
            ) : (
                <div className="flex-1 flex items-center justify-center text-[#86909c]">
                    请选择一个知识空间
                </div>
            )}
        </div>
    );
}
