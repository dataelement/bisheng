import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
    FileStatus,
    FileType,
    KnowledgeFile,
    KnowledgeSpace,
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
    pinSpaceApi,
    searchSpaceChildrenApi,
    unsubscribeSpaceApi,
    updateSpaceApi,
} from "~/api/knowledge";
import { submitShougangKnowledgeSpaceCreateApprovalApi } from "~/api/approval";
import { checkPermission } from "~/api/permission";
import { NotificationSeverity } from "~/common";
import { useConfirm, useToastContext } from "~/Providers";
import type { CreateKnowledgeSpaceFormData } from "../CreateKnowledgeSpaceDrawer";
import { useFileUpload } from "../hooks/useFileUpload";
import { triggerUrlDownload } from "../knowledgeUtils";
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
    resolvePreviewUrl,
    toNumericIds,
    toStatusNumbers,
    updateTreeNode,
} from "./utils";
import { DocumentPreview } from "./components/DocumentPreview";
import { FilePane } from "./components/FilePane";
import { PortalDialogs } from "./components/PortalDialogs";
import { PortalInfoDrawer } from "./components/PortalInfoDrawer";
import { SpaceSidebar } from "./components/SpaceSidebar";
import { ToolRail } from "./components/ToolRail";
import { usePortalApprovalBridge } from "./hooks/usePortalApprovalBridge";
import { usePortalSpaces } from "./hooks/usePortalSpaces";
import { usePortalUploadDialog } from "./hooks/usePortalUploadDialog";
import s from "./PortalKnowledgeWorkbench.module.css";

export default function PortalKnowledgeWorkbench() {
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const queryClient = useQueryClient();
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
    const [aiDialogOpen, setAiDialogOpen] = useState(false);
    const [summaryExpanded, setSummaryExpanded] = useState(false);
    const [tagModalOpen, setTagModalOpen] = useState(false);
    const [permissionOpen, setPermissionOpen] = useState(false);
    const [spacePermissionOpen, setSpacePermissionOpen] = useState(false);
    const [spacePermissionDialogSpace, setSpacePermissionDialogSpace] = useState<KnowledgeSpace | null>(null);
    const [createDrawerOpen, setCreateDrawerOpen] = useState(false);
    const [editingSpace, setEditingSpace] = useState<KnowledgeSpace | null>(null);
    const [pendingCreateLevel, setPendingCreateLevel] = useState<SpaceLevel>(SpaceLevel.PERSONAL);
    const [spaceMenuOpenId, setSpaceMenuOpenId] = useState<string | null>(null);
    const [treeNodes, setTreeNodes] = useState<PortalFileTreeNode[]>([]);
    const [treeLoading, setTreeLoading] = useState(false);
    const [treeRootPage, setTreeRootPage] = useState(1);
    const [treeRootTotal, setTreeRootTotal] = useState(0);
    const [treeRootLoadingMore, setTreeRootLoadingMore] = useState(false);
    const [searchMode, setSearchMode] = useState(false);
    const [searchResults, setSearchResults] = useState<KnowledgeFile[]>([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
    const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
    const [selectedFolderIds, setSelectedFolderIds] = useState<Set<string>>(new Set());
    const [deleteEntryIds, setDeleteEntryIds] = useState<Set<string>>(new Set());
    const [downloadEntryIds, setDownloadEntryIds] = useState<Set<string>>(new Set());
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
            showToast({ message: "最多置顶 5 个知识空间", severity: NotificationSeverity.INFO });
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
            showToast({ message: "知识空间已删除", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "删除知识空间失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, confirm, getNextActiveSpace, queryClient, showToast]);

    const handleLeaveSpace = useCallback(async (space: KnowledgeSpace) => {
        const ok = await confirm({
            title: "提示",
            description: "确认退出该知识空间？",
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
            showToast({ message: "已退出知识空间", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "退出知识空间失败", severity: NotificationSeverity.ERROR });
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
    const statusFilterNumbers = useMemo(
        () => toStatusNumbers(statusFilter),
        [statusFilter],
    );

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

    const loadRootTree = useCallback(async (page = 1, append = false, spaceId = activeSpace?.id) => {
        if (!spaceId) {
            setTreeNodes([]);
            setTreeRootTotal(0);
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
                file_status: statusFilterNumbers,
            });
            if (activeSpaceIdRef.current !== spaceId) return;
            setTreeNodes((prev) => append
                ? [...prev, ...res.data.map(createTreeNode)]
                : res.data.map(createTreeNode));
            setTreeRootPage(page);
            setTreeRootTotal(res.total);
        } catch {
            if (activeSpaceIdRef.current !== spaceId) return;
            if (!append) {
                setTreeNodes([]);
                setTreeRootTotal(0);
            }
            showToast({ message: "文件列表加载失败", severity: NotificationSeverity.ERROR });
        } finally {
            if (activeSpaceIdRef.current === spaceId) {
                setTreeLoading(false);
                setTreeRootLoadingMore(false);
            }
        }
    }, [activeSpace?.id, showToast, statusFilterNumbers]);

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
                total: res.total,
            })));
        } catch {
            if (activeSpaceIdRef.current !== spaceId) return;
            showToast({ message: "文件列表加载失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, currentFolderId, loadRootTree, showToast, statusFilterNumbers]);

    const fileUpload = useFileUpload({
        activeSpace,
        currentFolderId,
        currentPath,
        files: currentFolderNode ? currentFolderNode.children.map((node) => node.file) : treeNodes.map((node) => node.file),
        setFiles: setCurrentFolderFiles,
        setTotal: () => undefined,
        loadFiles: reloadFiles,
        currentPage: 1,
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
    const {
        uploadInputRef,
        uploadFolderInputRef,
        uploadDialogOpen,
        uploadStep,
        uploadFiles,
        uploadLocalFolderName,
        uploadFolderId,
        uploadFolderName,
        uploadFolderNodes,
        uploadFolderLoading,
        uploadSubmitting,
        uploadImporting,
        uploadReviewRows,
        uploadFolderOptions,
        setUploadDialogOpen,
        setUploadStep,
        setUploadReviewRows,
        resetUploadDialog,
        handleOpenUploadDialog,
        handleAddUploadFiles,
        handleAddUploadFolder,
        handleRemoveUploadFile,
        handleSelectUploadFolder,
        handleToggleUploadFolder,
        handleUploadNext,
        handleStartUploadImport,
    } = usePortalUploadDialog({
        activeSpace,
        setActiveSpace,
        uploadTargetSpace,
        canUploadInPortal,
        currentFolderId,
        currentFolderNode,
        currentPath,
        statusFilterNumbers,
        reloadFiles,
        showToast,
    });

    useEffect(() => {
        setSelectedFile(null);
        setActivePanel(null);
        setAiDialogOpen(false);
        setSummaryExpanded(false);
        setSearchText("");
        setSearchMode(false);
        setSearchResults([]);
        setSelectedFileIds(new Set());
        setSelectedFolderIds(new Set());
        setTreeNodes([]);
        setTreeRootPage(1);
        setTreeRootTotal(0);
        setCurrentFolderId(undefined);
        setCanCreateFolder(false);
        setCanUploadFile(false);
        if (activeSpace) {
            void loadRootTree(1, false, activeSpace.id);
        }
    }, [activeSpace?.id, loadRootTree]);

    useEffect(() => {
        if (!selectedFile) return;
        const exists = displayedFiles.some((file) => file.id === selectedFile.id);
        if (!exists) {
            setSelectedFile(null);
        }
    }, [displayedFiles, selectedFile]);

    useEffect(() => {
        setSummaryExpanded(false);
        setAiDialogOpen(false);
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
        const eligibleSourceSpace = activeSpace?.spaceLevel === SpaceLevel.TEAM || activeSpace?.spaceLevel === SpaceLevel.PERSONAL;
        const candidates = displayedFiles.filter((file) => (
            eligibleSourceSpace
            && !file.isCreating
            && file.type !== FileType.FOLDER
            && file.status === FileStatus.SUCCESS
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
        Promise.all(candidates.map(async (file) => {
            const result = await checkPermission(
                "knowledge_file",
                file.id,
                "can_edit",
                "upload_file",
                { signal: controller.signal },
            ).catch(() => ({ allowed: false }));
            return { id: file.id, allowed: Boolean(result.allowed) };
        })).then((results) => {
            if (cancelled) return;
            setPublishIds(new Set(results.filter((item) => item.allowed).map((item) => item.id)));
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
                setAiDialogOpen(false);
                return;
            }
            setSelectedFile(file);
        },
        [],
    );

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
                file_status: statusFilterNumbers,
            });
            if (activeSpaceIdRef.current !== spaceId) return;
            setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({
                ...item,
                children: res.data.map(createTreeNode),
                expanded: true,
                loaded: true,
                loading: false,
                page: 1,
                total: res.total,
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
    }, [activeSpace?.id, showToast, statusFilterNumbers]);

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
                file_status: statusFilterNumbers,
            });
            if (activeSpaceIdRef.current !== spaceId) return;
            setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({
                ...item,
                children: [...item.children, ...res.data.map(createTreeNode)],
                loading: false,
                loaded: true,
                page: nextPage,
                total: res.total,
            })));
        } catch {
            if (activeSpaceIdRef.current !== spaceId) return;
            setTreeNodes((prev) => updateTreeNode(prev, node.file.id, (item) => ({ ...item, loading: false })));
            showToast({ message: "加载更多失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, showToast, statusFilterNumbers]);

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

    const canPublishFile = useCallback((file: KnowledgeFile) => {
        return Boolean(
            activeSpace
            && (activeSpace.spaceLevel === SpaceLevel.TEAM || activeSpace.spaceLevel === SpaceLevel.PERSONAL)
            && file.type !== FileType.FOLDER
            && file.status === FileStatus.SUCCESS
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
                showToast({ message: "知识空间已更新", severity: NotificationSeverity.SUCCESS });
                return true;
            }

            const result = await submitShougangKnowledgeSpaceCreateApprovalApi({
                name: form.name,
                description: form.description,
                auth_type: authType,
                is_released: form.publishToSquare === "yes",
                space_level: form.spaceLevel,
                department_id: form.departmentId,
                user_group_id: form.userGroupId,
                auto_tag_enabled: form.autoTagEnabled,
                auto_tag_library_id: form.autoTagLibraryId, reason: form.reason,
            });

            if (result.created && result.space) {
                setActiveSpace(result.space);
                await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
                showToast({ message: "创建知识空间成功", severity: NotificationSeverity.SUCCESS });
                return true;
            }

            await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: "已提交申请", severity: NotificationSeverity.SUCCESS });
            return true;
        } catch (error) {
            const message = error instanceof Error && error.message ? error.message : "创建知识空间失败";
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

    return (
        <div className={s.workbench}>
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

            <FilePane
                activeSpaceName={activeSpace?.name}
                hasActiveSpace={Boolean(activeSpace)}
                searchText={searchText}
                searchMode={searchMode}
                searchLoading={searchLoading}
                treeLoading={treeLoading}
                treeRootLoadingMore={treeRootLoadingMore}
                treeRootHasMore={treeNodes.length < treeRootTotal}
                visibleTreeNodes={visibleTreeNodes}
                searchResults={searchResults}
                selectedFileId={selectedFile?.id}
                selectedFileIds={selectedFileIds}
                selectedFolderIds={selectedFolderIds}
                selectedCount={selectedCount}
                selectedDownloadable={selectedDownloadable}
                selectedDeletable={selectedDeletable}
                canBatchRetry={canBatchRetry}
                canUploadInPortal={canUploadInPortal}
                canCreateFolderInPortal={canCreateFolderInPortal}
                statusFilter={statusFilter}
                folderDraft={folderDraft}
                onFolderDraftChange={setFolderDraft}
                onSearchTextChange={(nextValue) => {
                    setSearchText(nextValue);
                    if (!nextValue.trim()) {
                        setSearchMode(false);
                        setSearchResults([]);
                        setSelectedFileIds(new Set());
                        setSelectedFolderIds(new Set());
                    }
                }}
                onSearch={() => void handleSearch()}
                onOpenUploadDialog={handleOpenUploadDialog}
                onShowUnavailable={showUnavailable}
                onCreateFolder={() => fileUpload.handleCreateFolder()}
                onToggleStatusFilter={handleToggleStatusFilter}
                onBatchDownload={() => void handleBatchDownload()}
                onBatchRetry={() => void handleBatchRetry()}
                onBatchDelete={() => void handleBatchDelete()}
                onLoadMoreRoot={() => void loadRootTree(treeRootPage + 1, true)}
                onConfirmCreateFolder={confirmCreateFolder}
                onCancelCreateFolder={fileUpload.handleCancelCreateFolder}
                onSelectFile={handleSelectFile}
                onToggleFileSelection={handleToggleFileSelection}
                canPublishFile={canPublishFile}
                onPublishFile={setPublishingFile}
                onToggleFolder={(node) => void handleToggleFolder(node)}
                onLoadMoreChildren={(node) => void handleLoadMoreChildren(node)}
            />

            <main className={s.documentArea}>
                <DocumentPreview
                    selectedFile={selectedFile}
                    documentPath={documentPath}
                    preview={preview}
                    summaryExpanded={summaryExpanded}
                    onOpenAi={() => {
                        setActivePanel(null);
                        setAiDialogOpen(true);
                    }}
                    onOpenTags={() => setTagModalOpen(true)}
                    onOpenShare={() => setActivePanel("share")}
                    onDownload={() => void handleDownloadSelected()}
                    onOpenPermission={() => setPermissionOpen(true)}
                    onCopyEncoding={() => void handleCopyFileEncoding()}
                    onToggleSummary={() => {
                        setActivePanel(null);
                        setSummaryExpanded((expanded) => !expanded);
                    }}
                />

                {selectedFile ? (
                    <PortalInfoDrawer
                        activePanel={activePanel}
                        activeSpace={activeSpace}
                        selectedFile={selectedFile}
                        documentPath={documentPath}
                        onClose={() => setActivePanel(null)}
                        onCopyShareLink={() => void copyShareLink()}
                    />
                ) : null}

                {selectedFile ? (
                    <ToolRail
                        activePanel={activePanel}
                        onTogglePanel={() => setActivePanel((current) => current ? null : "properties")}
                        onOpenPanel={setActivePanel}
                        onOpenPermission={() => {
                            setActivePanel(null);
                            setPermissionOpen(true);
                        }}
                    />
                ) : null}
            </main>

            <PortalDialogs
                activeSpace={activeSpace}
                selectedFile={selectedFile}
                documentPath={documentPath}
                tagModalOpen={tagModalOpen}
                onTagModalOpenChange={setTagModalOpen}
                onTagsSaved={() => {
                    setTagModalOpen(false);
                    void loadRootTree(1);
                }}
                permissionOpen={permissionOpen}
                onPermissionOpenChange={setPermissionOpen}
                approvalDialogOpen={approvalBridge.approvalDialogOpen}
                approvalDialogTarget={approvalBridge.approvalDialogTarget}
                onApprovalDialogOpenChange={approvalBridge.setApprovalDialogOpen}
                onApprovalDialogTargetChange={approvalBridge.setApprovalDialogTarget}
                notificationsOpen={approvalBridge.notificationsOpen}
                onNotificationsOpenChange={approvalBridge.setNotificationsOpen}
                aiDialogOpen={aiDialogOpen}
                onAiDialogOpenChange={setAiDialogOpen}
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
                    uploadFolderNodes,
                    uploadFolderLoading,
                    uploadSubmitting,
                    uploadImporting,
                    uploadReviewRows,
                    uploadFolderOptions,
                    onOpen: () => setUploadDialogOpen(true),
                    onClose: resetUploadDialog,
                    onAddUploadFiles: handleAddUploadFiles,
                    onAddUploadFolder: handleAddUploadFolder,
                    onRemoveUploadFile: handleRemoveUploadFile,
                    onSelectUploadFolder: handleSelectUploadFolder,
                    onToggleUploadFolder: (node) => void handleToggleUploadFolder(node),
                    onUploadNext: () => void handleUploadNext(),
                    onReviewRowsChange: setUploadReviewRows,
                    onBackToSelect: () => setUploadStep("select"),
                    onStartUploadImport: () => void handleStartUploadImport(),
                }}
                duplicateFiles={fileUpload.duplicateFiles}
                onDuplicateSkip={fileUpload.handleDuplicateSkip}
                onDuplicateOverwrite={fileUpload.handleDuplicateOverwrite}
            />
        </div>
    );
}
