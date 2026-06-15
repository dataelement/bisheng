import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
    FileStatus,
    FileType,
    KnowledgeFile,
    KnowledgeSpace,
    SortDirection,
    SortType,
    SpaceLevel,
    SpaceRole,
    VisibilityType,
    batchDeleteApi,
    batchDownloadApi,
    batchRetryApi,
    deleteSpaceApi,
    getFileDownloadApi,
    getFilePreviewApi,
    getSpaceChildrenApi,
    getSpaceInfoApi,
    importWebLinkApi,
    pinSpaceApi,
    searchSpaceChildrenApi,
    unsubscribeSpaceApi,
    updateFileEncoding,
    updateSpaceApi,
} from "~/api/knowledge";
import { checkPermission, canOpenPermissionDialog } from "~/api/permission";
import { NotificationSeverity } from "~/common";
import {
    Button,
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
} from "~/components/ui";
import { useGetBsConfig } from "~/hooks/queries/endpoints/queries";
import { useConfirm, useToastContext } from "~/Providers";
import { usePrefersMobileLayout } from "~/hooks";
import type { CreateKnowledgeSpaceFormData } from "../CreateKnowledgeSpaceDrawer";
import { useAiSplitPane } from "../hooks/useAiSplitPane";
import { useFileUpload } from "../hooks/useFileUpload";
import { triggerUrlDownload } from "../knowledgeUtils";
import { submitKnowledgeSpaceCreate } from "../createKnowledgeSpaceApproval";
import { TREE_PAGE_SIZE } from "./constants";
import type {
    PanelKey,
    PortalFileTreeNode,
    PreviewState,
    SpaceGroup,
    SpaceGroupKey,
} from "./types";
import {
    collectTreeFileIds,
    createTreeNode,
    extractExt,
    findTreeNode,
    findTreeNodePath,
    flattenTreeFiles,
    isFolder,
    isPreviewable,
    isRetryable,
    normalizePortalFileCategoryOptions,
    resolvePreviewUrl,
    toNumericIds,
    toStatusNumbers,
    updateTreeNode,
} from "./utils";
import { KnowledgeSpaceContent } from "../SpaceDetail";
import { KnowledgeAiPanel } from "../SpaceDetail/AiChat/KnowledgeAiPanel";
import type { SearchParams } from "../SpaceDetail/CompoundSearchInput";
import { PortalDialogs } from "./components/PortalDialogs";
import { PortalHeaderActions } from "./components/PortalHeaderActions";
import { PortalPreviewWorkspace } from "./components/PortalPreviewWorkspace";
import { PortalUploadedFilesDrawer } from "./components/PortalUploadedFilesDrawer";
import { SpaceSidebar } from "./components/SpaceSidebar";
import { usePortalApprovalBridge } from "./hooks/usePortalApprovalBridge";
import { usePortalDeepLink } from "./hooks/usePortalDeepLink";
import { usePortalSpaces } from "./hooks/usePortalSpaces";
import { usePortalUploadDialog } from "./hooks/usePortalUploadDialog";
import s from "./PortalKnowledgeWorkbench.module.css";

const getPortalSpaceLevel = (space?: KnowledgeSpace | null) => (
    space?.spaceLevel ?? (space as any)?.space_level
);

export default function PortalKnowledgeWorkbench() {
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const queryClient = useQueryClient();
    const [searchParams] = useSearchParams();
    const { data: bsConfig } = useGetBsConfig();
    const isH5 = usePrefersMobileLayout();
    const aiPane = useAiSplitPane();
    const groupRefs = useRef<Record<SpaceGroupKey, HTMLDivElement | null>>({
        public: null,
        department: null,
        team: null,
        personal: null,
    });
    const [activeSpace, setActiveSpace] = useState<KnowledgeSpace | null>(null);
    const [spaceSidebarCollapsed, setSpaceSidebarCollapsed] = useState(false);
    const [expandedGroups, setExpandedGroups] = useState<Record<SpaceGroupKey, boolean>>({
        public: true,
        department: true,
        team: true,
        personal: true,
    });
    const [selectedFile, setSelectedFile] = useState<KnowledgeFile | null>(null);
    const [searchText, setSearchText] = useState("");
    const [folderDraft, setFolderDraft] = useState("新建文件夹");
    const [activePanel, setActivePanel] = useState<PanelKey | null>(null);
    const [aiDrawerOpen, setAiDrawerOpen] = useState(false);
    const [summaryExpanded, setSummaryExpanded] = useState(false);
    const [tagModalOpen, setTagModalOpen] = useState(false);
    const [permissionOpen, setPermissionOpen] = useState(false);
    const [permissionTarget, setPermissionTarget] = useState<KnowledgeFile | null>(null);
    const [spacePermissionOpen, setSpacePermissionOpen] = useState(false);
    const [spacePermissionDialogSpace, setSpacePermissionDialogSpace] = useState<KnowledgeSpace | null>(null);
    const [createDrawerOpen, setCreateDrawerOpen] = useState(false);
    const [editingSpace, setEditingSpace] = useState<KnowledgeSpace | null>(null);
    const [pendingCreateLevel, setPendingCreateLevel] = useState<SpaceLevel>(SpaceLevel.PERSONAL);
    const [uploadedFilesOpen, setUploadedFilesOpen] = useState(false);
    const [webLinkDialogOpen, setWebLinkDialogOpen] = useState(false);
    const [webLinkUrl, setWebLinkUrl] = useState("");
    const [webLinkTitle, setWebLinkTitle] = useState("");
    const [webLinkSubmitting, setWebLinkSubmitting] = useState(false);
    const [spaceMenuOpenId, setSpaceMenuOpenId] = useState<string | null>(null);
    const [treeNodes, setTreeNodes] = useState<PortalFileTreeNode[]>([]);
    const [treeLoading, setTreeLoading] = useState(false);
    const [treeRootPage, setTreeRootPage] = useState(1);
    const [treeRootTotal, setTreeRootTotal] = useState(0);
    const [treeRootHasMore, setTreeRootHasMore] = useState(false);
    const [treeRootLoadingMore, setTreeRootLoadingMore] = useState(false);
    const [searchMode, setSearchMode] = useState(false);
    const [searchResults, setSearchResults] = useState<KnowledgeFile[]>([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
    const [sortBy, setSortBy] = useState<SortType | undefined>();
    const [sortDirection, setSortDirection] = useState<SortDirection | undefined>();
    const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
    const [selectedFolderIds, setSelectedFolderIds] = useState<Set<string>>(new Set());
    const [deleteEntryIds, setDeleteEntryIds] = useState<Set<string>>(new Set());
    const [downloadEntryIds, setDownloadEntryIds] = useState<Set<string>>(new Set());
    const [permissionEntryIds, setPermissionEntryIds] = useState<Set<string>>(new Set());
    const [canEditSelectedFileEncoding, setCanEditSelectedFileEncoding] = useState(false);
    const [publishEntryIds, setPublishEntryIds] = useState<Set<string>>(new Set());
    const [publishingFile, setPublishingFile] = useState<KnowledgeFile | null>(null);
    const [canCreateFolder, setCanCreateFolder] = useState(false);
    const [canUploadFile, setCanUploadFile] = useState(false);
    const [currentFolderId, setCurrentFolderId] = useState<string | undefined>();
    const [preview, setPreview] = useState<PreviewState>({
        loading: false,
        fileUrl: "",
        fileType: "",
        error: "",
    });
    const activeSpaceIdRef = useRef<string | undefined>();

    useEffect(() => {
        activeSpaceIdRef.current = activeSpace?.id;
    }, [activeSpace?.id]);

    const setPublishIds = useCallback((nextIds: Set<string>) => {
        setPublishEntryIds((prev) => {
            if (prev.size === nextIds.size && [...nextIds].every((id) => prev.has(id))) {
                return prev;
            }
            return nextIds;
        });
    }, []);

    const approvalBridge = usePortalApprovalBridge();

    const {
        groups,
        createOptionsLoading,
        createPermissionByLevel,
        selectableSpaces,
        spaceLoading,
        activeGroup,
        getSpacePermissions,
    } = usePortalSpaces({ activeSpace, setActiveSpace });

    const scrollToGroup = useCallback((groupKey: SpaceGroupKey) => {
        const run = () => {
            groupRefs.current[groupKey]?.scrollIntoView?.({ block: "start", behavior: "smooth" });
        };
        const schedule = typeof window !== "undefined" && window.requestAnimationFrame
            ? window.requestAnimationFrame.bind(window)
            : (callback: FrameRequestCallback) => window.setTimeout(callback, 0);
        schedule(() => schedule(run));
    }, []);

    const handleRestoreSidebar = useCallback((groupKey?: SpaceGroupKey) => {
        setSpaceSidebarCollapsed(false);
        if (!groupKey) return;

        const firstSpace = groups.find((group) => group.key === groupKey)?.spaces[0];
        if (firstSpace) {
            setActiveSpace(firstSpace);
        }
        setExpandedGroups((prev) => ({
            ...prev,
            [groupKey]: true,
        }));
        scrollToGroup(groupKey);
    }, [groups, scrollToGroup]);

    const handleOpenCreateSpace = useCallback((group: SpaceGroup) => {
        if (createOptionsLoading || !createPermissionByLevel[group.level]) return;
        setEditingSpace(null);
        setPendingCreateLevel(group.level);
        setCreateDrawerOpen(true);
    }, [createOptionsLoading, createPermissionByLevel]);

    const getNextActiveSpace = useCallback((spaceId: string) => {
        return selectableSpaces.find((space) => space.id !== spaceId) ?? null;
    }, [selectableSpaces]);

    const handleOpenSpaceSettings = useCallback(async (space: KnowledgeSpace) => {
        try {
            const detail = await getSpaceInfoApi(space.id);
            setEditingSpace({ ...space, ...detail, id: space.id });
        } catch {
            setEditingSpace(space);
        }
        setCreateDrawerOpen(true);
    }, []);

    const handleOpenSpaceMembers = useCallback((space: KnowledgeSpace) => {
        if (space.spaceLevel === SpaceLevel.PERSONAL) return;
        setSpacePermissionDialogSpace(space);
        setSpacePermissionOpen(true);
    }, []);

    const handleSpacePermissionChanged = useCallback(async () => {
        const targetSpace = spacePermissionDialogSpace;
        if (!targetSpace) return;
        await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
        try {
            const detail = await getSpaceInfoApi(targetSpace.id);
            const latestSpace = { ...targetSpace, ...detail, id: targetSpace.id };
            setSpacePermissionDialogSpace(latestSpace);
            setActiveSpace((prev) => prev?.id === targetSpace.id ? latestSpace : prev);
        } catch {
            // 权限变更后的刷新失败不阻塞弹窗，列表会通过 invalidateQueries 继续更新。
        }
    }, [queryClient, spacePermissionDialogSpace]);

    const handlePinSpace = useCallback(async (space: KnowledgeSpace, pinned: boolean, group: SpaceGroup) => {
        if (pinned && group.spaces.filter((item) => item.isPinned).length >= 5) {
            showToast({ message: "最多置顶 5 个知识库", severity: NotificationSeverity.INFO });
            return;
        }
        try {
            await pinSpaceApi(space.id, pinned);
            setActiveSpace((prev) => prev?.id === space.id ? { ...prev, isPinned: pinned } : prev);
            await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: pinned ? "已置顶" : "已取消置顶", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "操作失败", severity: NotificationSeverity.ERROR });
        }
    }, [queryClient, showToast]);

    const handleDeleteSpace = useCallback(async (space: KnowledgeSpace) => {
        const ok = await confirm({
            title: "提示",
            description: "确认执行该操作？",
            confirmText: "删除",
            cancelText: "取消",
        });
        if (!ok) return;

        try {
            await deleteSpaceApi(space.id);
            if (activeSpace?.id === space.id) {
                setActiveSpace(getNextActiveSpace(space.id));
            }
            await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: "知识库已删除", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "删除知识库失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, confirm, getNextActiveSpace, queryClient, showToast]);

    const handleLeaveSpace = useCallback(async (space: KnowledgeSpace) => {
        const ok = await confirm({
            title: "提示",
            description: "确认退出该知识库？",
            confirmText: "退出",
            cancelText: "取消",
        });
        if (!ok) return;

        try {
            await unsubscribeSpaceApi(space.id);
            if (activeSpace?.id === space.id) {
                setActiveSpace(getNextActiveSpace(space.id));
            }
            await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: "已退出知识库", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "退出知识库失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, confirm, getNextActiveSpace, queryClient, showToast]);

    const isActiveSpaceAdmin = activeSpace?.role === SpaceRole.CREATOR || activeSpace?.role === SpaceRole.ADMIN;
    const currentFolderNode = useMemo(
        () => currentFolderId ? findTreeNode(treeNodes, currentFolderId) : null,
        [currentFolderId, treeNodes],
    );
    const currentPath = useMemo(
        () => currentFolderId ? findTreeNodePath(treeNodes, currentFolderId) : [],
        [currentFolderId, treeNodes],
    );
    const isActiveSpacePersonal = getPortalSpaceLevel(activeSpace) === SpaceLevel.PERSONAL;
    const statusFilterNumbers = useMemo(
        () => toStatusNumbers(statusFilter),
        [statusFilter],
    );
    const canManageSelectedFilePermission = Boolean(
        selectedFile && !isActiveSpacePersonal && (isActiveSpaceAdmin || permissionEntryIds.has(selectedFile.id)),
    );
    const visiblePermissionEntryIds = useMemo(
        () => isActiveSpacePersonal ? new Set<string>() : permissionEntryIds,
        [isActiveSpacePersonal, permissionEntryIds],
    );

    useEffect(() => {
        const file = selectedFile;
        if (!activeSpace || !file || isFolder(file) || file.isCreating) {
            setCanEditSelectedFileEncoding(false);
            return;
        }
        if (isActiveSpaceAdmin) {
            setCanEditSelectedFileEncoding(true);
            return;
        }

        let cancelled = false;
        const controller = new AbortController();
        setCanEditSelectedFileEncoding(false);
        checkPermission(
            "knowledge_file",
            file.id,
            "can_edit",
            "rename_file",
            { signal: controller.signal },
        ).then((result) => {
            if (!cancelled) {
                setCanEditSelectedFileEncoding(Boolean(result?.allowed));
            }
        }).catch(() => {
            if (!cancelled) {
                setCanEditSelectedFileEncoding(false);
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [activeSpace?.id, isActiveSpaceAdmin, selectedFile?.id, selectedFile?.type, selectedFile?.isCreating]);

    const setRootFiles = useCallback<Dispatch<SetStateAction<KnowledgeFile[]>>>((value) => {
        setTreeNodes((prev) => {
            const currentFiles = prev.map((node) => node.file);
            const nextFiles = typeof value === "function"
                ? (value as (prev: KnowledgeFile[]) => KnowledgeFile[])(currentFiles)
                : value;
            return nextFiles.map(createTreeNode);
        });
    }, []);

    const setCurrentFolderFiles = useCallback<Dispatch<SetStateAction<KnowledgeFile[]>>>((value) => {
        const folderId = currentFolderId;
        if (!folderId) {
            setRootFiles(value);
            return;
        }
        setTreeNodes((prev) => updateTreeNode(prev, folderId, (node) => {
            const currentFiles = node.children.map((child) => child.file);
            const nextFiles = typeof value === "function"
                ? (value as (prev: KnowledgeFile[]) => KnowledgeFile[])(currentFiles)
                : value;
            return {
                ...node,
                children: nextFiles.map(createTreeNode),
                loaded: true,
                expanded: true,
                total: Math.max(node.total, nextFiles.length),
            };
        }));
    }, [currentFolderId, setRootFiles]);

    const setCurrentFileListTotal = useCallback<Dispatch<SetStateAction<number>>>((value) => {
        const folderId = currentFolderId;
        if (!folderId) {
            setTreeRootTotal(value);
            return;
        }
        setTreeNodes((prev) => updateTreeNode(prev, folderId, (node) => ({
            ...node,
            total: typeof value === "function"
                ? (value as (prev: number) => number)(node.total)
                : value,
        })));
    }, [currentFolderId]);

    const markPendingDeletion = useCallback((_ids: Array<string | number>) => {
        // 门户侧文件列表由当前页面状态驱动，删除后的抑制逻辑交给原生列表乐观更新。
    }, []);

    const clearPendingDeletion = useCallback((_ids: Array<string | number>) => {
        // 与 markPendingDeletion 成对传入，供原生知识空间列表的批量删除流程调用。
    }, []);

    const patchFileById = useCallback((fileId: string, updater: (file: KnowledgeFile) => KnowledgeFile) => {
        setTreeNodes((prev) => updateTreeNode(prev, fileId, (node) => ({
            ...node,
            file: updater(node.file),
        })));
        setSearchResults((prev) => prev.map((file) => file.id === fileId ? updater(file) : file));
        setSelectedFile((prev) => prev?.id === fileId ? updater(prev) : prev);
    }, []);

    const loadRootTree = useCallback(async (page = 1, append = false, spaceId = activeSpace?.id) => {
        if (!spaceId) {
            setTreeNodes([]);
            setTreeRootTotal(0);
            setTreeRootHasMore(false);
            return;
        }
        if (append) {
            setTreeRootLoadingMore(true);
        } else {
            setTreeLoading(true);
        }
        try {
            const res = await getSpaceChildrenApi({
                space_id: spaceId,
                page,
                page_size: TREE_PAGE_SIZE,
                order_field: sortBy,
                order_sort: sortDirection,
                file_status: statusFilterNumbers,
            });
            if (activeSpaceIdRef.current !== spaceId) return;
            const total = (res as any).total ?? res.data.length;
            setTreeNodes((prev) => append
                ? [...prev, ...res.data.map(createTreeNode)]
                : res.data.map(createTreeNode));
            setTreeRootPage(page);
            setTreeRootTotal(total);
            setTreeRootHasMore(Boolean((res as any).has_more ?? (page * TREE_PAGE_SIZE < total)));
        } catch {
            if (activeSpaceIdRef.current !== spaceId) return;
            if (!append) {
                setTreeNodes([]);
                setTreeRootTotal(0);
                setTreeRootHasMore(false);
            }
            showToast({ message: "文件列表加载失败", severity: NotificationSeverity.ERROR });
        } finally {
            if (activeSpaceIdRef.current === spaceId) {
                setTreeLoading(false);
                setTreeRootLoadingMore(false);
            }
        }
    }, [activeSpace?.id, showToast, sortBy, sortDirection, statusFilterNumbers]);

    const reloadFiles = useCallback(async () => {
        setSearchMode(false);
        setSearchResults([]);
        const spaceId = activeSpace?.id;
        if (!spaceId) return;
        if (!currentFolderId) {
            await loadRootTree(1, false, spaceId);
            return;
        }
        const folderId = currentFolderId;
        try {
            const res = await getSpaceChildrenApi({
                space_id: spaceId,
                parent_id: folderId,
                page: 1,
                page_size: TREE_PAGE_SIZE,
                order_field: sortBy,
                order_sort: sortDirection,
                file_status: statusFilterNumbers,
            });
            if (activeSpaceIdRef.current !== spaceId) return;
            setTreeNodes((prev) => updateTreeNode(prev, folderId, (node) => ({
                ...node,
                children: res.data.map(createTreeNode),
                expanded: true,
                loaded: true,
                loading: false,
                page: 1,
                total: (res as any).total ?? res.data.length,
            })));
        } catch {
            if (activeSpaceIdRef.current !== spaceId) return;
            showToast({ message: "文件列表加载失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, currentFolderId, loadRootTree, showToast, sortBy, sortDirection, statusFilterNumbers]);

    const fileUpload = useFileUpload({
        activeSpace,
        currentFolderId,
        currentPath,
        files: currentFolderNode ? currentFolderNode.children.map((node) => node.file) : treeNodes.map((node) => node.file),
        setFiles: setCurrentFolderFiles,
        setTotal: setCurrentFileListTotal,
        loadFiles: reloadFiles,
        currentPage: 1,
        markPendingDeletion,
        clearPendingDeletion,
    });

    const transientRootFiles = useMemo(
        () => [
            ...(fileUpload.creatingFolder ? [fileUpload.creatingFolder] : []),
            ...fileUpload.uploadingFiles,
        ].filter((file) => !file.parentId),
        [fileUpload.creatingFolder, fileUpload.uploadingFiles],
    );
    const transientFolderFiles = useMemo(
        () => [
            ...(fileUpload.creatingFolder ? [fileUpload.creatingFolder] : []),
            ...fileUpload.uploadingFiles,
        ].filter((file) => file.parentId && file.parentId === currentFolderId),
        [currentFolderId, fileUpload.creatingFolder, fileUpload.uploadingFiles],
    );
    const visibleTreeNodes = useMemo(() => {
        const withFolderTransients = currentFolderId && transientFolderFiles.length
            ? updateTreeNode(treeNodes, currentFolderId, (node) => ({
                ...node,
                expanded: true,
                children: [
                    ...transientFolderFiles.map(createTreeNode),
                    ...node.children,
                ],
            }))
            : treeNodes;
        return [
            ...transientRootFiles.map(createTreeNode),
            ...withFolderTransients,
        ];
    }, [currentFolderId, transientFolderFiles, transientRootFiles, treeNodes]);
    const visibleTreeFiles = useMemo(
        () => flattenTreeFiles(visibleTreeNodes),
        [visibleTreeNodes],
    );
    const currentFolderFiles = useMemo(
        () => currentFolderNode ? currentFolderNode.children.map((node) => node.file) : treeNodes.map((node) => node.file),
        [currentFolderNode, treeNodes],
    );
    const currentFileListPage = currentFolderNode?.page ?? treeRootPage;
    const currentFileListTotal = currentFolderNode?.total ?? treeRootTotal;
    const currentFileListHasMore = searchMode
        ? false
        : currentFolderNode
            ? currentFolderNode.children.length < currentFolderNode.total
            : treeRootHasMore || treeNodes.length < treeRootTotal;
    const currentFileListLoading = treeLoading || searchLoading || treeRootLoadingMore || Boolean(currentFolderNode?.loading);
    const displayedFiles = searchMode ? searchResults : visibleTreeFiles;
    const selectedFiles = useMemo(
        () => displayedFiles.filter((file) => selectedFileIds.has(file.id) || selectedFolderIds.has(file.id)),
        [displayedFiles, selectedFileIds, selectedFolderIds],
    );
    const selectedCount = selectedFiles.length;
    const selectedDownloadable = selectedFiles.length > 0 && selectedFiles.every((file) => downloadEntryIds.has(file.id));
    const selectedDeletable = selectedFiles.length > 0 && selectedFiles.every((file) => deleteEntryIds.has(file.id));
    const retryableSelectedFiles = selectedFiles.filter(isRetryable);
    const canBatchRetry = Boolean(isActiveSpaceAdmin && retryableSelectedFiles.length > 0);
    const uploadTargetSpace = activeSpace ?? selectableSpaces[0] ?? null;
    const isUploadTargetAdmin = uploadTargetSpace?.role === SpaceRole.CREATOR || uploadTargetSpace?.role === SpaceRole.ADMIN;
    const canUploadInPortal = Boolean(uploadTargetSpace && (isUploadTargetAdmin || canUploadFile));
    const canCreateFolderInPortal = Boolean(activeSpace && !searchMode && (isActiveSpaceAdmin || canCreateFolder));
    const fileCategoryOptions = useMemo(
        () => normalizePortalFileCategoryOptions((bsConfig as any)?.shougang?.file_encoding?.document_types),
        [bsConfig],
    );
    const fileEncodingPrefix = useMemo(() => {
        const prefix = (bsConfig as any)?.shougang?.prefix;
        return typeof prefix === "string" && prefix.trim() ? prefix.trim() : "SGGF";
    }, [bsConfig]);

    useEffect(() => {
        const handlePortalMessage = (event: MessageEvent) => {
            const type = event.data?.type;
            if (type === "shougang-portal:open-my-upload" || type === "shougang-portal:open-my-uploads") {
                setUploadedFilesOpen(true);
            }
        };
        window.addEventListener("message", handlePortalMessage);
        return () => window.removeEventListener("message", handlePortalMessage);
    }, []);

    const {
        uploadInputRef,
        uploadFolderInputRef,
        uploadDialogOpen,
        uploadStep,
        uploadFiles,
        uploadLocalFolderName,
        uploadFolderId,
        uploadFolderName,
        uploadFolderSelection,
        uploadFolderNodes,
        uploadFolderLoading,
        uploadSubmitting,
        uploadImporting,
        uploadReviewRows,
        uploadFolderOptions,
        duplicateFiles,
        fileCategoryCode,
        fileCategoryOptions: resolvedFileCategoryOptions,
        businessDomainCode,
        uploadTagOptions,
        selectedUploadTagValues,
        uploadTagLoading,
        setUploadDialogOpen,
        setUploadStep,
        setUploadReviewRows,
        resetUploadDialog,
        handleOpenUploadDialog,
        handleAddUploadFiles,
        handleAddUploadFolder,
        handleRemoveUploadFile,
        handleSelectFileCategory,
        handleSelectBusinessDomain,
        handleToggleUploadTag,
        handleClearUploadTags,
        handleSelectUploadFolder,
        handleUseAiUploadFolder,
        handleToggleUploadFolder,
        handleUploadNext,
        handleStartUploadImport,
        handleDuplicateSkip,
        handleDuplicateOverwrite,
    } = usePortalUploadDialog({
        activeSpace,
        setActiveSpace,
        uploadTargetSpace,
        canUploadInPortal,
        currentFolderId,
        currentFolderNode,
        currentPath,
        statusFilterNumbers,
        fileCategoryOptions,
        reloadFiles,
        onUploaded: () => setUploadedFilesOpen(true),
        showToast,
    });

    useEffect(() => {
        setSelectedFile(null);
        setActivePanel(null);
        setAiDrawerOpen(false);
        setSummaryExpanded(false);
        setSearchText("");
        setSearchMode(false);
        setSearchResults([]);
        setSelectedFileIds(new Set());
        setSelectedFolderIds(new Set());
        setTreeNodes([]);
        setTreeRootPage(1);
        setTreeRootTotal(0);
        setTreeRootHasMore(false);
        setCurrentFolderId(undefined);
        setCanCreateFolder(false);
        setCanUploadFile(false);
        if (activeSpace) {
            void loadRootTree(1, false, activeSpace.id);
        }
    }, [activeSpace?.id, loadRootTree]);

    usePortalDeepLink({
        searchParams,
        activeSpace,
        activeSpaceIdRef,
        selectableSpaces,
        displayedFiles,
        statusFilterNumbers,
        setActiveSpace,
        setCurrentFolderId,
        setSelectedFileIds,
        setSelectedFolderIds,
        setSearchText,
        setSearchMode,
        setSearchResults,
        setSearchLoading,
        setSelectedFile,
    });

    useEffect(() => {
        if (!selectedFile) return;
        const exists = displayedFiles.some((file) => file.id === selectedFile.id);
        if (!exists) {
            setSelectedFile(null);
        }
    }, [displayedFiles, selectedFile]);

    useEffect(() => {
        if (!permissionTarget) return;
        const exists = displayedFiles.some((file) => file.id === permissionTarget.id);
        if (!exists) {
            setPermissionTarget(null);
            setPermissionOpen(false);
        }
    }, [displayedFiles, permissionTarget]);

    useEffect(() => {
        setSummaryExpanded(false);
        setAiDrawerOpen(false);
    }, [selectedFile?.id]);

    useEffect(() => {
        if (currentFolderId && !findTreeNode(treeNodes, currentFolderId)) {
            setCurrentFolderId(undefined);
        }
    }, [currentFolderId, treeNodes]);

    useEffect(() => {
        if (isActiveSpaceAdmin) {
            setCanCreateFolder(Boolean(activeSpace));
            setCanUploadFile(Boolean(activeSpace));
            return;
        }
        if (!activeSpace) {
            setCanCreateFolder(false);
            setCanUploadFile(false);
            return;
        }
        const spaceId = activeSpace.id;
        const targetFolderId = currentFolderId;
        const objectType = targetFolderId ? "folder" : "knowledge_space";
        const objectId = targetFolderId || spaceId;
        let cancelled = false;
        const controller = new AbortController();
        Promise.allSettled([
            checkPermission(objectType, objectId, "can_edit", "create_folder", { signal: controller.signal }),
            checkPermission(objectType, objectId, "can_edit", "upload_file", { signal: controller.signal }),
        ]).then(([createFolderResult, uploadFileResult]) => {
            if (cancelled || activeSpace?.id !== spaceId || currentFolderId !== targetFolderId) return;
            setCanCreateFolder(createFolderResult.status === "fulfilled" && Boolean(createFolderResult.value?.allowed));
            setCanUploadFile(uploadFileResult.status === "fulfilled" && Boolean(uploadFileResult.value?.allowed));
        });
        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [activeSpace?.id, currentFolderId, isActiveSpaceAdmin]);

    const permissionProbeKey = useMemo(
        () => displayedFiles
            .filter((file) => !file.isCreating && /^\d+$/.test(String(file.id)))
            .map((file) => `${file.id}:${file.type}`)
            .join("|"),
        [displayedFiles],
    );

    useEffect(() => {
        const candidates = displayedFiles.filter((file) => !file.isCreating && /^\d+$/.test(String(file.id)));
        if (isActiveSpacePersonal) {
            setPermissionEntryIds(new Set());
            return;
        }
        if (isActiveSpaceAdmin) {
            const ids = new Set(candidates.map((file) => file.id));
            setPermissionEntryIds(ids);
            return;
        }
        if (!activeSpace || candidates.length === 0) {
            setPermissionEntryIds(new Set());
            return;
        }
        let cancelled = false;
        const controller = new AbortController();
        Promise.all(candidates.map(async (file) => {
            const resourceType = file.type === FileType.FOLDER ? "folder" : "knowledge_file";
            const allowed = await canOpenPermissionDialog(resourceType, file.id, {
                signal: controller.signal,
            }).catch(() => false);
            return allowed ? file.id : null;
        })).then((ids) => {
            if (cancelled) return;
            setPermissionEntryIds(new Set(ids.filter((id): id is string => Boolean(id))));
        });
        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [activeSpace?.id, isActiveSpaceAdmin, isActiveSpacePersonal, permissionProbeKey]);

    useEffect(() => {
        if (!isActiveSpacePersonal) return;
        setPermissionTarget(null);
        setPermissionOpen(false);
        setActivePanel((current) => current === "permission" ? null : current);
    }, [isActiveSpacePersonal]);

    useEffect(() => {
        const candidates = displayedFiles.filter((file) => !file.isCreating && /^\d+$/.test(String(file.id)));
        if (isActiveSpaceAdmin) {
            const ids = new Set(candidates.map((file) => file.id));
            setDownloadEntryIds(ids);
            setDeleteEntryIds(ids);
            return;
        }
        if (!activeSpace || candidates.length === 0) {
            setDownloadEntryIds(new Set());
            setDeleteEntryIds(new Set());
            return;
        }
        let cancelled = false;
        const controller = new AbortController();
        Promise.all(candidates.map(async (file) => {
            const resourceType = file.type === FileType.FOLDER ? "folder" : "knowledge_file";
            const downloadPermission = file.type === FileType.FOLDER ? "download_folder" : "download_file";
            const deletePermission = file.type === FileType.FOLDER ? "delete_folder" : "delete_file";
            const [downloadResult, deleteResult] = await Promise.all([
                checkPermission(resourceType, file.id, "can_read", downloadPermission, { signal: controller.signal }).catch(() => ({ allowed: false })),
                checkPermission(resourceType, file.id, "can_delete", deletePermission, { signal: controller.signal }).catch(() => ({ allowed: false })),
            ]);
            return {
                id: file.id,
                canDownload: downloadResult.allowed,
                canDelete: deleteResult.allowed,
            };
        })).then((results) => {
            if (cancelled) return;
            setDownloadEntryIds(new Set(results.filter((item) => item.canDownload).map((item) => item.id)));
            setDeleteEntryIds(new Set(results.filter((item) => item.canDelete).map((item) => item.id)));
        });
        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [activeSpace?.id, isActiveSpaceAdmin, permissionProbeKey]);

    useEffect(() => {
        const eligibleSourceSpace = Boolean(activeSpace && activeSpace.spaceLevel !== SpaceLevel.PUBLIC);
        const candidates = displayedFiles.filter((file) => (
            eligibleSourceSpace
            && !file.isCreating
            && file.type !== FileType.FOLDER
            && /^\d+$/.test(String(file.id))
        ));
        if (!activeSpace || candidates.length === 0) {
            setPublishIds(new Set());
            return;
        }
        if (isActiveSpaceAdmin) {
            setPublishIds(new Set(candidates.map((file) => file.id)));
            return;
        }

        let cancelled = false;
        const controller = new AbortController();
        checkPermission(
            "knowledge_space",
            activeSpace.id,
            "can_edit",
            "upload_file",
            { signal: controller.signal },
        ).catch(() => ({ allowed: false })).then((result) => {
            if (cancelled) return;
            setPublishIds(result.allowed ? new Set(candidates.map((file) => file.id)) : new Set());
        });
        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [activeSpace?.id, activeSpace?.spaceLevel, displayedFiles, isActiveSpaceAdmin, permissionProbeKey, setPublishIds]);

    useEffect(() => {
        if (!fileUpload.creatingFolder) return;
        setFolderDraft("新建文件夹");
    }, [fileUpload.creatingFolder]);

    useEffect(() => {
        if (!activeSpace || !selectedFile || isFolder(selectedFile)) {
            setPreview({ loading: false, fileUrl: "", fileType: "", error: "" });
            return;
        }

        if (!isPreviewable(selectedFile)) {
            setPreview({
                loading: false,
                fileUrl: "",
                fileType: "",
                error: "文件尚未完成解析，暂时不可预览。",
            });
            return;
        }

        let cancelled = false;
        setPreview({
            loading: true,
            fileUrl: "",
            fileType: extractExt(selectedFile.name),
            error: "",
        });

        getFilePreviewApi(activeSpace.id, selectedFile.id)
            .then((res) => {
                if (cancelled) return;
                const nextUrl = res.preview_url || res.original_url;
                if (!nextUrl) {
                    setPreview({
                        loading: false,
                        fileUrl: "",
                        fileType: extractExt(selectedFile.name),
                        error: "未获取到文件预览地址。",
                    });
                    return;
                }
                setPreview({
                    loading: false,
                    fileUrl: resolvePreviewUrl(nextUrl),
                    fileType: extractExt(selectedFile.name, nextUrl),
                    error: "",
                });
            })
            .catch(() => {
                if (cancelled) return;
                setPreview({
                    loading: false,
                    fileUrl: "",
                    fileType: extractExt(selectedFile.name),
                    error: "文件预览加载失败。",
                });
            });

        return () => {
            cancelled = true;
        };
    }, [activeSpace, selectedFile]);

    const showUnavailable = useCallback(() => {
        showToast({ message: "暂未开放", severity: NotificationSeverity.INFO });
    }, [showToast]);

    const handleOpenWebLinkDialog = useCallback(() => {
        if (!canUploadInPortal || !activeSpace) {
            showToast({ message: "无上传权限", severity: NotificationSeverity.ERROR });
            return;
        }
        setWebLinkDialogOpen(true);
    }, [activeSpace, canUploadInPortal, showToast]);

    const handleImportWebLink = useCallback(async () => {
        const spaceId = activeSpace?.id;
        const normalizedUrl = webLinkUrl.trim();
        if (!spaceId) return;
        if (!normalizedUrl) {
            showToast({ message: "请输入网页链接", severity: NotificationSeverity.ERROR });
            return;
        }
        try {
            const parsed = new URL(normalizedUrl);
            if (!["http:", "https:"].includes(parsed.protocol)) {
                showToast({ message: "仅支持 http 或 https 链接", severity: NotificationSeverity.ERROR });
                return;
            }
        } catch {
            showToast({ message: "请输入有效的网页链接", severity: NotificationSeverity.ERROR });
            return;
        }

        setWebLinkSubmitting(true);
        try {
            const created = await importWebLinkApi(spaceId, {
                url: normalizedUrl,
                title: webLinkTitle.trim() || undefined,
                parent_id: currentFolderId ? Number(currentFolderId) : null,
            });
            setSearchMode(false);
            setSearchResults([]);
            setCurrentFolderFiles((prev) => [created, ...prev]);
            setCurrentFileListTotal((prev) => prev + 1);
            setWebLinkUrl("");
            setWebLinkTitle("");
            setWebLinkDialogOpen(false);
            showToast({ message: "网页链接已开始导入", severity: NotificationSeverity.SUCCESS });
        } catch (error: any) {
            showToast({
                message: error?.message || "网页链接导入失败",
                severity: NotificationSeverity.ERROR,
            });
        } finally {
            setWebLinkSubmitting(false);
        }
    }, [
        activeSpace?.id,
        currentFolderId,
        setCurrentFileListTotal,
        setCurrentFolderFiles,
        showToast,
        webLinkTitle,
        webLinkUrl,
    ]);

    const handleSearch = useCallback(async () => {
        const spaceId = activeSpace?.id;
        if (!spaceId) return;
        const keyword = searchText.trim();
        setSelectedFileIds(new Set());
        setSelectedFolderIds(new Set());
        if (!keyword) {
            setSearchMode(false);
            setSearchResults([]);
            return;
        }
        setSearchMode(true);
        setSearchLoading(true);
        try {
            const res = await searchSpaceChildrenApi({
                space_id: spaceId,
                keyword,
                page: 1,
                page_size: TREE_PAGE_SIZE,
                file_status: statusFilterNumbers,
            });
            if (activeSpaceIdRef.current !== spaceId) return;
            setSearchResults(res.data);
        } catch {
            if (activeSpaceIdRef.current !== spaceId) return;
            setSearchResults([]);
            showToast({ message: "搜索文件失败", severity: NotificationSeverity.ERROR });
        } finally {
            if (activeSpaceIdRef.current === spaceId) {
                setSearchLoading(false);
            }
        }
    }, [activeSpace?.id, searchText, showToast, statusFilterNumbers]);

    const handleNativeSearch = useCallback(async (params: SearchParams) => {
        const spaceId = activeSpace?.id;
        if (!spaceId) return;
        const keyword = params.keyword.trim();
        setSearchText(keyword);
        setSelectedFileIds(new Set());
        setSelectedFolderIds(new Set());
        if (!keyword && params.tagIds.length === 0) {
            setSearchMode(false);
            setSearchResults([]);
            return;
        }
        setSearchMode(true);
        setSearchLoading(true);
        try {
            const res = await searchSpaceChildrenApi({
                space_id: spaceId,
                parent_id: currentFolderId,
                keyword,
                tag_ids: params.tagIds,
                page: 1,
                page_size: TREE_PAGE_SIZE,
                order_field: sortBy,
                order_sort: sortDirection,
                file_status: statusFilterNumbers,
            });
            if (activeSpaceIdRef.current !== spaceId) return;
            setSearchResults(res.data);
            setTreeRootTotal(res.total);
        } catch {
            if (activeSpaceIdRef.current !== spaceId) return;
            setSearchResults([]);
            showToast({ message: "搜索文件失败", severity: NotificationSeverity.ERROR });
        } finally {
            if (activeSpaceIdRef.current === spaceId) {
                setSearchLoading(false);
            }
        }
    }, [activeSpace?.id, currentFolderId, showToast, sortBy, sortDirection, statusFilterNumbers]);

    const handleNativeStatusFilter = useCallback((nextStatus: FileStatus[]) => {
        setStatusFilter(nextStatus);
        setSearchText("");
        setSearchMode(false);
        setSearchResults([]);
        setSelectedFile(null);
        setSelectedFileIds(new Set());
        setSelectedFolderIds(new Set());
    }, []);

    const handleNativeSort = useCallback((nextSortBy: SortType | undefined, nextDirection: SortDirection | undefined) => {
        setSortBy(nextSortBy);
        setSortDirection(nextDirection);
        setSearchMode(false);
        setSearchResults([]);
    }, []);

    const handleToggleStatusFilter = useCallback((status: FileStatus, checked: boolean) => {
        setStatusFilter((prev) => {
            const exists = prev.includes(status);
            if (checked && !exists) return [...prev, status];
            if (!checked && exists) return prev.filter((item) => item !== status);
            return prev;
        });
        setSearchText("");
        setSearchMode(false);
        setSearchResults([]);
        setSelectedFileIds(new Set());
        setSelectedFolderIds(new Set());
        setSelectedFile(null);
        setCurrentFolderId(undefined);
    }, []);

    const handleSelectFile = useCallback(
        (file: KnowledgeFile) => {
            if (file.isCreating) return;
            if (isFolder(file)) {
                setSelectedFile(null);
                setActivePanel(null);
                setAiDrawerOpen(false);
                return;
            }
            setSelectedFile(file);
        },
        [],
    );

    const handleBackToFileList = useCallback(() => {
        setSelectedFile(null);
        setActivePanel(null);
        setAiDrawerOpen(false);
        setSummaryExpanded(false);
        setPreview({ loading: false, fileUrl: "", fileType: "", error: "" });
    }, []);

    const handleToggleFileSelection = useCallback((file: KnowledgeFile, checked: boolean) => {
        const update = (prev: Set<string>) => {
            const next = new Set(prev);
            if (checked) {
                next.add(file.id);
            } else {
                next.delete(file.id);
            }
            return next;
        };
        if (isFolder(file)) {
            setSelectedFolderIds(update);
        } else {
            setSelectedFileIds(update);
        }
    }, []);

    const handleToggleFolder = useCallback(async (node: PortalFileTreeNode) => {
        const spaceId = activeSpace?.id;
        if (!spaceId || node.file.isCreating) return;
        setCurrentFolderId(node.file.id);
        if (node.expanded) {
            const childIds = collectTreeFileIds(node.children);
            setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({ ...item, expanded: false })));
            setSelectedFileIds((prev) => {
                const next = new Set(prev);
                childIds.forEach((id) => next.delete(id));
                return next;
            });
            setSelectedFolderIds((prev) => {
                const next = new Set(prev);
                childIds.forEach((id) => next.delete(id));
                return next;
            });
            return;
        }
        if (node.loaded) {
            setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({ ...item, expanded: true })));
            return;
        }

        setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({
            ...item,
            expanded: true,
            loading: true,
        })));
        try {
            const res = await getSpaceChildrenApi({
                space_id: spaceId,
                parent_id: node.file.id,
                page: 1,
                page_size: TREE_PAGE_SIZE,
                order_field: sortBy,
                order_sort: sortDirection,
                file_status: statusFilterNumbers,
            });
            if (activeSpaceIdRef.current !== spaceId) return;
            const total = (res as any).total ?? res.data.length;
            setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({
                ...item,
                children: res.data.map(createTreeNode),
                expanded: true,
                loaded: true,
                loading: false,
                page: 1,
                total,
            })));
        } catch {
            if (activeSpaceIdRef.current !== spaceId) return;
            setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({
                ...item,
                expanded: false,
                loading: false,
            })));
            showToast({ message: "文件夹加载失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, showToast, sortBy, sortDirection, statusFilterNumbers]);

    const handleLoadMoreChildren = useCallback(async (node: PortalFileTreeNode) => {
        const spaceId = activeSpace?.id;
        if (!spaceId || node.loading) return;
        const nextPage = node.page + 1;
        setCurrentFolderId(node.file.id);
        setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({ ...item, loading: true })));
        try {
            const res = await getSpaceChildrenApi({
                space_id: spaceId,
                parent_id: node.file.id,
                page: nextPage,
                page_size: TREE_PAGE_SIZE,
                order_field: sortBy,
                order_sort: sortDirection,
                file_status: statusFilterNumbers,
            });
            if (activeSpaceIdRef.current !== spaceId) return;
            const total = (res as any).total ?? node.total;
            setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({
                ...item,
                children: [...item.children, ...res.data.map(createTreeNode)],
                loading: false,
                loaded: true,
                page: nextPage,
                total,
            })));
        } catch {
            if (activeSpaceIdRef.current !== spaceId) return;
            setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({ ...item, loading: false })));
            showToast({ message: "加载更多失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, showToast, sortBy, sortDirection, statusFilterNumbers]);

    const handleNavigateFolder = useCallback(async (folderId?: string) => {
        const spaceId = activeSpace?.id;
        if (!spaceId) return;
        setSearchMode(false);
        setSearchResults([]);
        setSearchText("");
        setSelectedFile(null);
        setSelectedFileIds(new Set());
        setSelectedFolderIds(new Set());

        if (!folderId) {
            setCurrentFolderId(undefined);
            if (treeNodes.length === 0) {
                await loadRootTree(1, false, spaceId);
            }
            return;
        }

        setCurrentFolderId(folderId);
        const node = findTreeNode(treeNodes, folderId);
        if (node?.loaded) {
            setTreeNodes((prev) => updateTreeNode(prev, folderId, (item) => ({
                ...item,
                expanded: true,
            })));
            return;
        }

        setTreeNodes((prev) => updateTreeNode(prev, folderId, (item) => ({
            ...item,
            expanded: true,
            loading: true,
        })));
        try {
            const res = await getSpaceChildrenApi({
                space_id: spaceId,
                parent_id: folderId,
                page: 1,
                page_size: TREE_PAGE_SIZE,
                order_field: sortBy,
                order_sort: sortDirection,
                file_status: statusFilterNumbers,
            });
            if (activeSpaceIdRef.current !== spaceId) return;
            const total = (res as any).total ?? res.data.length;
            setTreeNodes((prev) => updateTreeNode(prev, folderId, (item) => ({
                ...item,
                children: res.data.map(createTreeNode),
                expanded: true,
                loaded: true,
                loading: false,
                page: 1,
                total,
            })));
        } catch {
            if (activeSpaceIdRef.current !== spaceId) return;
            setCurrentFolderId(undefined);
            setTreeNodes((prev) => updateTreeNode(prev, folderId, (item) => ({
                ...item,
                loading: false,
            })));
            showToast({ message: "文件夹加载失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, loadRootTree, showToast, sortBy, sortDirection, statusFilterNumbers, treeNodes]);

    const handleNativePageChange = useCallback((page: number) => {
        if (searchMode) return;
        if (currentFolderNode) {
            void handleLoadMoreChildren(currentFolderNode);
            return;
        }
        void loadRootTree(page, page > 1);
    }, [currentFolderNode, handleLoadMoreChildren, loadRootTree, searchMode]);

    const confirmCreateFolder = useCallback(() => {
        if (!fileUpload.creatingFolder) return;
        const nextName = folderDraft.trim();
        if (!nextName) {
            fileUpload.handleCancelCreateFolder();
            return;
        }
        void fileUpload.handleRenameFile(fileUpload.creatingFolder.id, nextName);
    }, [fileUpload, folderDraft]);

    const handleDownloadSelected = useCallback(async () => {
        if (!activeSpace || !selectedFile || isFolder(selectedFile)) return;
        try {
            const res = await getFileDownloadApi(activeSpace.id, selectedFile.id);
            const downloadUrl = res.original_url || res.preview_url;
            if (!downloadUrl) {
                showToast({ message: "未获取到下载地址", severity: NotificationSeverity.ERROR });
                return;
            }
            triggerUrlDownload(downloadUrl, selectedFile.name);
        } catch {
            showToast({ message: "下载地址获取失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace, selectedFile, showToast]);

    const clearBatchSelection = useCallback(() => {
        setSelectedFileIds(new Set());
        setSelectedFolderIds(new Set());
    }, []);

    const handleBatchDownload = useCallback(async () => {
        if (!activeSpace || selectedFiles.length === 0) return;
        if (!selectedDownloadable) {
            showToast({ message: "所选内容无下载权限", severity: NotificationSeverity.ERROR });
            return;
        }
        const files = selectedFiles.filter((file) => !isFolder(file));
        const folders = selectedFiles.filter(isFolder);
        try {
            const url = await batchDownloadApi(activeSpace.id, {
                file_ids: files.length ? toNumericIds(files) : undefined,
                folder_ids: folders.length ? toNumericIds(folders) : undefined,
            });
            if (!url) {
                showToast({ message: "未获取到下载地址", severity: NotificationSeverity.ERROR });
                return;
            }
            triggerUrlDownload(url, `${activeSpace.name || "knowledge"}_files.zip`);
        } catch {
            showToast({ message: "批量下载失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace, selectedDownloadable, selectedFiles, showToast]);

    const handleBatchDelete = useCallback(async () => {
        if (!activeSpace || selectedFiles.length === 0) return;
        if (!selectedDeletable) {
            showToast({ message: "所选内容无删除权限", severity: NotificationSeverity.ERROR });
            return;
        }
        const ok = await confirm({
            title: "确认删除所选内容？",
            description: "删除后不可恢复。",
            confirmText: "删除",
            cancelText: "取消",
        });
        if (!ok) return;
        const files = selectedFiles.filter((file) => !isFolder(file));
        const folders = selectedFiles.filter(isFolder);
        try {
            await batchDeleteApi(activeSpace.id, {
                file_ids: files.length ? toNumericIds(files) : undefined,
                folder_ids: folders.length ? toNumericIds(folders) : undefined,
            });
            clearBatchSelection();
            setSelectedFile((prev) => prev && selectedFiles.some((file) => file.id === prev.id) ? null : prev);
            await loadRootTree(1);
            showToast({ message: "批量删除成功", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "批量删除失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace, clearBatchSelection, confirm, loadRootTree, selectedDeletable, selectedFiles, showToast]);

    const handleBatchRetry = useCallback(async () => {
        if (!activeSpace || retryableSelectedFiles.length === 0) return;
        try {
            await batchRetryApi(activeSpace.id, toNumericIds(retryableSelectedFiles));
            clearBatchSelection();
            await loadRootTree(1);
            showToast({ message: "已开始重试", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "批量重试失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace, clearBatchSelection, loadRootTree, retryableSelectedFiles, showToast]);

    const copyShareLink = useCallback(async () => {
        if (!activeSpace) return;
        const baseUrl = `${window.location.origin}${__APP_ENV__.BASE_URL || ""}`.replace(/\/$/, "");
        const shareLink = `${baseUrl}/knowledge/share/${activeSpace.id}`;
        try {
            await navigator.clipboard.writeText(shareLink);
            showToast({ message: "分享链接已复制", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "复制失败，请重试", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace, showToast]);

    const handleCopyFileEncoding = useCallback(async () => {
        const fileEncoding = selectedFile?.fileEncoding?.trim();
        if (!fileEncoding) {
            showToast({ message: "暂无文件编码", severity: NotificationSeverity.INFO });
            return;
        }

        try {
            await navigator.clipboard.writeText(fileEncoding);
            showToast({ message: "文件编码已复制", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "复制失败，请重试", severity: NotificationSeverity.ERROR });
        }
    }, [selectedFile?.fileEncoding, showToast]);

    const handleUpdateSelectedFileEncoding = useCallback(async (newEncoding: string) => {
        if (!activeSpace || !selectedFile || !canEditSelectedFileEncoding) return;

        try {
            await updateFileEncoding(String(selectedFile.spaceId || activeSpace.id), selectedFile.id, newEncoding);
            patchFileById(selectedFile.id, (file) => ({
                ...file,
                fileEncoding: newEncoding,
            }));
            showToast({ message: "编码更新成功", severity: NotificationSeverity.SUCCESS });
        } catch (error) {
            showToast({ message: "编码更新失败", severity: NotificationSeverity.ERROR });
            throw error;
        }
    }, [
        activeSpace,
        canEditSelectedFileEncoding,
        patchFileById,
        selectedFile,
        showToast,
    ]);

    const canShowPublishFile = useCallback((file: KnowledgeFile) => {
        return Boolean(
            activeSpace
            && activeSpace.spaceLevel !== SpaceLevel.PUBLIC
            && file.type !== FileType.FOLDER
            && publishEntryIds.has(file.id),
        );
    }, [activeSpace, publishEntryIds]);

    const handleConfirmCreateSpace = useCallback(async (form: CreateKnowledgeSpaceFormData) => {
        try {
            const authType =
                form.joinPolicy === "public"
                    ? VisibilityType.PUBLIC
                    : form.joinPolicy === "review"
                        ? VisibilityType.APPROVAL
                        : VisibilityType.PRIVATE;
            if (editingSpace) {
                const updated = await updateSpaceApi(editingSpace.id, {
                    name: form.name,
                    description: form.description,
                    auth_type: authType,
                    is_released: form.publishToSquare === "yes",
                    auto_tag_enabled: form.autoTagEnabled,
                    auto_tag_library_id: form.autoTagLibraryId,
                });
                setActiveSpace((prev) => prev?.id === updated.id ? { ...updated, role: prev.role } : prev);
                await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
                showToast({ message: "知识库已更新", severity: NotificationSeverity.SUCCESS });
                return true;
            }

            const result = await submitKnowledgeSpaceCreate(form);

            if (result.created && result.space) {
                setActiveSpace(result.space);
                await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
                showToast({ message: "创建知识库成功", severity: NotificationSeverity.SUCCESS });
                return true;
            }

            await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: "已提交申请", severity: NotificationSeverity.SUCCESS });
            return { showSuccess: false };
        } catch (error) {
            const message = error instanceof Error && error.message ? error.message : "创建知识库失败";
            showToast({ message, severity: NotificationSeverity.ERROR });
            return false;
        }
    }, [editingSpace, queryClient, showToast]);

    const documentPath = useMemo(() => {
        const names = [
            "全部知识库",
            activeGroup?.title,
            activeSpace?.name,
            selectedFile?.path || selectedFile?.name,
        ].filter(Boolean);
        return names.join("/");
    }, [activeGroup?.title, activeSpace?.name, selectedFile?.name, selectedFile?.path]);
    const aiContextLabel = currentFolderId ? "文件夹" : "知识库";

    return (
        <div className={s.workbench}>
            {!aiDrawerOpen ? (
                <>
                    <SpaceSidebar
                        groups={groups}
                        activeSpaceId={activeSpace?.id}
                        collapsed={spaceSidebarCollapsed}
                        expandedGroups={expandedGroups}
                        groupRefs={groupRefs}
                        createOptionsLoading={createOptionsLoading}
                        createPermissionByLevel={createPermissionByLevel}
                        spaceLoading={spaceLoading}
                        spaceMenuOpenId={spaceMenuOpenId}
                        getSpacePermissions={getSpacePermissions}
                        onRestoreSidebar={handleRestoreSidebar}
                        onCollapseSidebar={() => setSpaceSidebarCollapsed(true)}
                        onToggleGroup={(groupKey) => setExpandedGroups((prev) => ({ ...prev, [groupKey]: !prev[groupKey] }))}
                        onOpenCreateSpace={handleOpenCreateSpace}
                        onSelectSpace={setActiveSpace}
                        onSpaceMenuOpenChange={(spaceId, open) => setSpaceMenuOpenId(open ? spaceId : null)}
                        onOpenSpaceSettings={(space) => void handleOpenSpaceSettings(space)}
                        onOpenSpaceMembers={handleOpenSpaceMembers}
                        onPinSpace={(space, pinned, group) => void handlePinSpace(space, pinned, group)}
                        onDeleteSpace={(space) => void handleDeleteSpace(space)}
                        onLeaveSpace={(space) => void handleLeaveSpace(space)}
                    />

                    {!selectedFile ? (
                        <main className={s.portalNativeWorkspace} data-testid="portal-file-workspace">
                            {activeSpace ? (
                                <div ref={aiPane.splitContainerRef} className="flex h-full min-w-0 flex-1 overflow-hidden">
                                    {isH5 && aiPane.showAiAssistant ? (
                                        <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-white">
                                            <KnowledgeAiPanel
                                                spaceId={String(activeSpace.id)}
                                                folderId={currentFolderId}
                                                contextLabel={aiContextLabel}
                                                onClose={() => aiPane.setShowAiAssistant(false)}
                                            />
                                        </div>
                                    ) : (
                                        <>
                                            <div
                                                style={{ width: aiPane.showAiAssistant ? `${aiPane.aiSplitWidth}px` : "100%" }}
                                                className="flex h-full min-h-0 min-w-0 flex-shrink-0 flex-col overflow-hidden"
                                            >
                                                <KnowledgeSpaceContent
                                                    space={activeSpace}
                                                    files={searchMode ? searchResults : currentFolderFiles}
                                                    currentPage={currentFileListPage}
                                                    pageSize={TREE_PAGE_SIZE}
                                                    total={currentFileListTotal}
                                                    hasMore={currentFileListHasMore}
                                                    onPageChange={handleNativePageChange}
                                                    loading={currentFileListLoading}
                                                    onSearch={(params) => void handleNativeSearch(params)}
                                                    onFilterStatus={handleNativeStatusFilter}
                                                    onSort={handleNativeSort}
                                                    onNavigateFolder={(folderId) => void handleNavigateFolder(folderId)}
                                                    onUploadFile={(files) => fileUpload.handleUploadFile(files)}
                                                    onUploadFolder={(files, options) => fileUpload.handleUploadFolder(files, options)}
                                                    onCreateFolder={() => fileUpload.handleCreateFolder()}
                                                    onDownloadFile={() => undefined}
                                                    onRenameFile={(fileId, newName) => void fileUpload.handleRenameFile(fileId, newName)}
                                                    onDeleteFile={(fileId) => void fileUpload.handleDeleteFile(fileId)}
                                                    onEditTags={(fileId) => void fileUpload.handleEditTags(fileId)}
                                                    onRetryFile={() => void reloadFiles()}
                                                    currentPath={currentPath}
                                                    currentFolderId={currentFolderId}
                                                    uploadingFiles={fileUpload.uploadingFiles}
                                                    creatingFolder={fileUpload.creatingFolder}
                                                    onCancelCreateFolder={fileUpload.handleCancelCreateFolder}
                                                    onToggleAiAssistant={aiPane.handleToggleAiAssistant}
                                                    isAiAssistantOpen={aiPane.showAiAssistant}
                                                    onGoKnowledgeSquare={showUnavailable}
                                                    onPreviewFile={handleSelectFile}
                                                    afterSearchActions={(
                                                        <PortalHeaderActions
                                                            canUpload={canUploadInPortal}
                                                            canCreateFolder={canCreateFolderInPortal}
                                                            statusFilter={statusFilter}
                                                            onOpenUploadDialog={handleOpenUploadDialog}
                                                            onOpenWebLinkDialog={handleOpenWebLinkDialog}
                                                            onShowUnavailable={showUnavailable}
                                                            onCreateFolder={() => fileUpload.handleCreateFolder()}
                                                            onToggleStatusFilter={handleToggleStatusFilter}
                                                        />
                                                    )}
                                                    hideNativeAddMenu
                                                    hideNativeStatusFilter
                                                    hideShareButton
                                                    hideFilePermissionActions={isActiveSpacePersonal}
                                                    enableEncodingClassification
                                                    fileCategoryOptions={fileCategoryOptions}
                                                    encodingPrefix={fileEncodingPrefix}
                                                    markPendingDeletion={markPendingDeletion}
                                                    clearPendingDeletion={clearPendingDeletion}
                                                    setFiles={setCurrentFolderFiles}
                                                    setTotal={setCurrentFileListTotal}
                                                />
                                            </div>

                                            {!isH5 && aiPane.showAiAssistant && (
                                                <div className="relative z-20 w-px min-w-px max-w-px flex-none shrink-0">
                                                    <div
                                                        onMouseDown={aiPane.startSplitResize}
                                                        className="group absolute inset-y-0 left-1/2 z-10 flex w-4 -translate-x-1/2 cursor-col-resize justify-center"
                                                    >
                                                        <div className="pointer-events-none w-px self-stretch bg-[#e5e6eb] transition-colors duration-150 group-hover:bg-primary group-active:bg-primary" />
                                                    </div>
                                                </div>
                                            )}

                                            {!isH5 && aiPane.showAiAssistant && (
                                                <div className="flex h-full min-w-[360px] flex-1 bg-white">
                                                    <KnowledgeAiPanel
                                                        spaceId={String(activeSpace.id)}
                                                        folderId={currentFolderId}
                                                        contextLabel={aiContextLabel}
                                                        onClose={() => aiPane.setShowAiAssistant(false)}
                                                    />
                                                </div>
                                            )}
                                        </>
                                    )}
                                </div>
                            ) : spaceLoading ? (
                                <div className={s.stateBox}>
                                    <div className={s.stateTitle}>正在加载知识库...</div>
                                </div>
                            ) : (
                                <div className={s.stateBox}>
                                    <div className={s.stateTitle}>暂无可用知识库</div>
                                    <div>请先创建或加入知识库。</div>
                                </div>
                            )}
                        </main>
                    ) : null}
                </>
            ) : null}

            {selectedFile ? (
                <PortalPreviewWorkspace
                    activePanel={activePanel}
                    activeSpace={activeSpace}
                    aiDrawerOpen={aiDrawerOpen}
                    canEditEncoding={canEditSelectedFileEncoding}
                    canManagePermission={canManageSelectedFilePermission}
                    documentPath={documentPath}
                    isPersonalSpace={isActiveSpacePersonal}
                    preview={preview}
                    selectedFile={selectedFile}
                    summaryExpanded={summaryExpanded}
                    onAiDrawerOpenChange={setAiDrawerOpen}
                    onBackToFileList={handleBackToFileList}
                    onCopyEncoding={() => void handleCopyFileEncoding()}
                    onCopyShareLink={() => void copyShareLink()}
                    onDownload={() => void handleDownloadSelected()}
                    fileCategoryOptions={fileCategoryOptions}
                    encodingPrefix={fileEncodingPrefix}
                    onUpdateEncoding={(newEncoding) => handleUpdateSelectedFileEncoding(newEncoding)}
                    onOpenPermission={() => {
                        if (!canManageSelectedFilePermission) return;
                        setPermissionTarget(selectedFile);
                        setPermissionOpen(true);
                    }}
                    onOpenTags={() => setTagModalOpen(true)}
                    onPanelChange={setActivePanel}
                    onToggleSummary={() => {
                        setActivePanel(null);
                        setSummaryExpanded((expanded) => !expanded);
                    }}
                />
            ) : null}

            <PortalDialogs
                activeSpace={activeSpace}
                selectedFile={selectedFile}
                permissionTarget={permissionTarget}
                documentPath={documentPath}
                tagModalOpen={tagModalOpen}
                onTagModalOpenChange={setTagModalOpen}
                onTagsSaved={() => {
                    setTagModalOpen(false);
                    void loadRootTree(1);
                }}
                permissionResourceType={permissionTarget && isFolder(permissionTarget) ? "folder" : "knowledge_file"}
                permissionOpen={permissionOpen}
                onPermissionOpenChange={(open) => {
                    setPermissionOpen(open);
                    if (!open) setPermissionTarget(null);
                }}
                approvalDialogOpen={approvalBridge.approvalDialogOpen}
                approvalDialogTarget={approvalBridge.approvalDialogTarget}
                onApprovalDialogOpenChange={approvalBridge.setApprovalDialogOpen}
                onApprovalDialogTargetChange={approvalBridge.setApprovalDialogTarget}
                notificationsOpen={approvalBridge.notificationsOpen}
                onNotificationsOpenChange={approvalBridge.setNotificationsOpen}
                publishingFile={publishingFile}
                onPublishingFileChange={setPublishingFile}
                spacePermissionDialogSpace={spacePermissionDialogSpace}
                spacePermissionOpen={spacePermissionOpen}
                onSpacePermissionOpenChange={setSpacePermissionOpen}
                onSpacePermissionChanged={handleSpacePermissionChanged}
                createDrawerOpen={createDrawerOpen}
                onCreateDrawerOpenChange={(open) => {
                    setCreateDrawerOpen(open);
                    if (!open) setEditingSpace(null);
                }}
                onConfirmCreateSpace={handleConfirmCreateSpace}
                editingSpace={editingSpace}
                pendingCreateLevel={pendingCreateLevel}
                showSuccessManageMembers={(spaceLevel) => spaceLevel !== SpaceLevel.PERSONAL}
                onViewCreatedSpace={() => setCreateDrawerOpen(false)}
                onManageEditingSpaceMembers={() => {
                    setCreateDrawerOpen(false);
                    if (editingSpace) handleOpenSpaceMembers(editingSpace);
                }}
                uploadDialogProps={{
                    open: uploadDialogOpen,
                    step: uploadStep,
                    activeSpaceName: activeSpace?.name,
                    uploadInputRef,
                    uploadFolderInputRef,
                    uploadFiles,
                    uploadLocalFolderName,
                    uploadFolderId,
                    uploadFolderName,
                    uploadFolderSelection,
                    uploadFolderNodes,
                    uploadFolderLoading,
                    uploadSubmitting,
                    uploadImporting,
                    uploadReviewRows,
                    uploadFolderOptions,
                    fileCategoryCode,
                    fileCategoryOptions: resolvedFileCategoryOptions,
                    businessDomainCode,
                    uploadTagOptions,
                    selectedUploadTagValues,
                    uploadTagLoading,
                    onOpen: () => setUploadDialogOpen(true),
                    onClose: resetUploadDialog,
                    onAddUploadFiles: handleAddUploadFiles,
                    onAddUploadFolder: handleAddUploadFolder,
                    onRemoveUploadFile: handleRemoveUploadFile,
                    onSelectFileCategory: handleSelectFileCategory,
                    onSelectBusinessDomain: handleSelectBusinessDomain,
                    onToggleUploadTag: handleToggleUploadTag,
                    onClearUploadTags: handleClearUploadTags,
                    onSelectUploadFolder: handleSelectUploadFolder,
                    onUseAiUploadFolder: handleUseAiUploadFolder,
                    onToggleUploadFolder: (node) => void handleToggleUploadFolder(node),
                    onUploadNext: () => void handleUploadNext(),
                    onReviewRowsChange: setUploadReviewRows,
                    onBackToSelect: () => setUploadStep("select"),
                    onStartUploadImport: () => void handleStartUploadImport(),
                }}
                duplicateFiles={duplicateFiles}
                onDuplicateSkip={handleDuplicateSkip}
                onDuplicateOverwrite={handleDuplicateOverwrite}
            />
            <PortalUploadedFilesDrawer
                open={uploadedFilesOpen}
                onOpenChange={setUploadedFilesOpen}
                onRecordsChanged={() => reloadFiles()}
                showToast={showToast}
                fileCategoryOptions={fileCategoryOptions}
                encodingPrefix={fileEncodingPrefix}
            />
            <Dialog open={webLinkDialogOpen} onOpenChange={(open) => {
                if (webLinkSubmitting) return;
                setWebLinkDialogOpen(open);
            }}>
                <DialogContent className="max-w-[520px]">
                    <DialogHeader>
                        <DialogTitle>网页链接</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4">
                        <label className="block space-y-2 text-sm text-[#1d2129]">
                            <span className="font-medium">链接地址</span>
                            <Input
                                value={webLinkUrl}
                                onChange={(event) => setWebLinkUrl(event.currentTarget.value)}
                                placeholder="https://example.com/page"
                                disabled={webLinkSubmitting}
                            />
                        </label>
                        <label className="block space-y-2 text-sm text-[#1d2129]">
                            <span className="font-medium">显示名称</span>
                            <Input
                                value={webLinkTitle}
                                onChange={(event) => setWebLinkTitle(event.currentTarget.value)}
                                placeholder="留空则自动读取网页标题"
                                disabled={webLinkSubmitting}
                            />
                        </label>
                    </div>
                    <DialogFooter>
                        <Button
                            variant="outline"
                            onClick={() => setWebLinkDialogOpen(false)}
                            disabled={webLinkSubmitting}
                        >
                            取消
                        </Button>
                        <Button onClick={() => void handleImportWebLink()} disabled={webLinkSubmitting}>
                            {webLinkSubmitting ? "导入中..." : "导入"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
