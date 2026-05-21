import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
    Bot,
    Brain,
    ChevronDown,
    ChevronRight,
    ChevronsLeft,
    ChevronsRight,
    Copy,
    Database,
    Download,
    FileArchive,
    FileCode2,
    FileText,
    Folder,
    FolderPlus,
    Globe2,
    History,
    Import,
    Link2,
    LogOut,
    LockKeyhole,
    MoreHorizontal,
    PanelRight,
    Pin,
    PinOff,
    Plus,
    Search,
    Settings,
    Settings2,
    Share2,
    ShieldCheck,
    Sparkles,
    Tags,
    Upload,
    UsersRound,
    X,
} from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Button,
} from "~/components/ui";
import {
    FileStatus,
    FileType,
    GroupedKnowledgeSpaces,
    KnowledgeFile,
    KnowledgeSpace,
    SpaceLevel,
    SpaceRole,
    SpaceSortType,
    VisibilityType,
    batchDeleteApi,
    batchDownloadApi,
    batchRetryApi,
    createSpaceApi,
    deleteSpaceApi,
    getFileDownloadApi,
    getFilePreviewApi,
    getCreateSpaceOptionsApi,
    getGroupedSpacesApi,
    getSpaceChildrenApi,
    getSpaceInfoApi,
    pinSpaceApi,
    searchSpaceChildrenApi,
    unsubscribeSpaceApi,
    updateSpaceApi,
} from "~/api/knowledge";
import { checkPermission } from "~/api/permission";
import { NotificationSeverity } from "~/common";
import { useConfirm, useToastContext } from "~/Providers";
import {
    DropdownMenu,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import {
    SidebarListMoreMenuContent,
    SidebarListMoreMenuDivider,
    sidebarListMoreMenuDangerIconClassName,
    sidebarListMoreMenuDangerItemClassName,
    sidebarListMoreMenuDangerLabelClassName,
    sidebarListMoreMenuIconClassName,
    sidebarListMoreMenuItemClassName,
    sidebarListMoreMenuLabelClassName,
} from "~/components/SidebarListMoreMenu";
import FilePreview from "../FilePreview";
import { CreateKnowledgeSpaceDrawer, type CreateKnowledgeSpaceFormData } from "../CreateKnowledgeSpaceDrawer";
import { EditTagsModal } from "../SpaceDetail/EditTagsModal";
import { KnowledgeAiPanel } from "../SpaceDetail/AiChat/KnowledgeAiPanel";
import { KnowledgeSpaceShareDialog } from "../SpaceDetail/KnowledgeSpaceShareDialog";
import {
    hasKnowledgeSpacePermission,
    useKnowledgeSpaceActionPermissions,
} from "../hooks/useKnowledgeSpacePermissions";
import { useFileUpload } from "../hooks/useFileUpload";
import { formatTime, triggerUrlDownload } from "../knowledgeUtils";
import s from "./PortalKnowledgeWorkbench.module.css";

type SpaceGroupKey = "public" | "department" | "team" | "personal";
type PanelKey = "details" | "summary" | "tags" | "permission" | "share" | "ai" | "features";

interface SpaceGroup {
    key: SpaceGroupKey;
    title: string;
    level: SpaceLevel;
    iconSrc: string;
    spaces: KnowledgeSpace[];
}

interface PreviewState {
    loading: boolean;
    fileUrl: string;
    fileType: string;
    error: string;
}

interface PortalFileTreeNode {
    file: KnowledgeFile;
    children: PortalFileTreeNode[];
    expanded: boolean;
    loaded: boolean;
    loading: boolean;
    page: number;
    total: number;
}

const EMPTY_GROUPED_SPACES: GroupedKnowledgeSpaces = {
    publicSpaces: [],
    departmentSpaces: [],
    teamSpaces: [],
    personalSpaces: [],
};

const TREE_PAGE_SIZE = 100;

const GROUP_ICON_SRC: Record<SpaceGroupKey, string> = {
    public: "/assets/knowledge-portal/space-public.png",
    department: "/assets/knowledge-portal/space-department.png",
    team: "/assets/knowledge-portal/space-team.png",
    personal: "/assets/knowledge-portal/space-personal.png",
};

const DISABLED_FEATURES = [
    { label: "导入网页", icon: Globe2 },
    { label: "Markdown 在线发布", icon: FileCode2 },
    { label: "API 导入", icon: Database },
    { label: "DWG/PDF 图纸专项", icon: FileArchive },
    { label: "智能入库", icon: Sparkles },
    { label: "复杂版本管理", icon: History },
    { label: "分段规则", icon: Settings2 },
];

function isFolder(file: KnowledgeFile) {
    return file.type === FileType.FOLDER;
}

function isPreviewable(file: KnowledgeFile) {
    if (isFolder(file)) return false;
    return !file.status || file.status === FileStatus.SUCCESS || file.status === FileStatus.VIOLATION;
}

function formatFileSize(size?: number) {
    if (!size || size <= 0) return "-";
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
    return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function extractExt(fileName: string, fileUrl = "") {
    const source = fileName || fileUrl.split("?")[0] || "";
    const ext = source.split(".").pop()?.toLowerCase() || "";
    return ext || "txt";
}

function resolvePreviewUrl(url: string) {
    if (!url) return "";
    if (/^https?:\/\//.test(url)) return url;
    const baseUrl = typeof __APP_ENV__ !== "undefined" ? __APP_ENV__.BASE_URL : "";
    return `${window.location.origin}${baseUrl}${url}`;
}

function resolveAssetUrl(path: string) {
    const baseUrl = typeof __APP_ENV__ !== "undefined" ? __APP_ENV__.BASE_URL || "" : "";
    return `${baseUrl.replace(/\/$/, "")}${path}`;
}

function statusText(file: KnowledgeFile) {
    switch (file.status) {
        case FileStatus.UPLOADING:
            return "上传中";
        case FileStatus.PROCESSING:
            return "解析中";
        case FileStatus.WAITING:
            return "排队中";
        case FileStatus.REBUILDING:
            return "重建中";
        case FileStatus.SUCCESS:
            return "成功";
        case FileStatus.FAILED:
            return "失败";
        case FileStatus.TIMEOUT:
            return "超时";
        case FileStatus.VIOLATION:
            return "违规";
        default:
            return "";
    }
}

function createTreeNode(file: KnowledgeFile): PortalFileTreeNode {
    return {
        file,
        children: [],
        expanded: false,
        loaded: false,
        loading: false,
        page: 1,
        total: 0,
    };
}

function flattenTreeFiles(nodes: PortalFileTreeNode[]): KnowledgeFile[] {
    return nodes.flatMap((node) => [
        node.file,
        ...(node.expanded ? flattenTreeFiles(node.children) : []),
    ]);
}

function collectTreeFileIds(nodes: PortalFileTreeNode[]): string[] {
    return nodes.flatMap((node) => [node.file.id, ...collectTreeFileIds(node.children)]);
}

function findTreeNode(nodes: PortalFileTreeNode[], fileId: string): PortalFileTreeNode | null {
    for (const node of nodes) {
        if (node.file.id === fileId) return node;
        const child = findTreeNode(node.children, fileId);
        if (child) return child;
    }
    return null;
}

function findTreeNodePath(
    nodes: PortalFileTreeNode[],
    fileId: string,
    path: Array<{ id?: string; name: string }> = [],
): Array<{ id?: string; name: string }> {
    for (const node of nodes) {
        const nextPath = [...path, { id: node.file.id, name: node.file.name }];
        if (node.file.id === fileId) return nextPath;
        const childPath = findTreeNodePath(node.children, fileId, nextPath);
        if (childPath.length) return childPath;
    }
    return [];
}

function updateTreeNode(
    nodes: PortalFileTreeNode[],
    fileId: string,
    updater: (node: PortalFileTreeNode) => PortalFileTreeNode,
): PortalFileTreeNode[] {
    return nodes.map((node) => {
        if (node.file.id === fileId) {
            return updater(node);
        }
        if (!node.children.length) return node;
        return {
            ...node,
            children: updateTreeNode(node.children, fileId, updater),
        };
    });
}

function folderCountText(file: KnowledgeFile) {
    if (file.successFileNum === undefined || file.fileNum === undefined) return "";
    return `(${file.successFileNum}/${file.fileNum})`;
}

function isRetryable(file: KnowledgeFile) {
    if (file.status === FileStatus.FAILED || file.status === FileStatus.VIOLATION) return true;
    if (isFolder(file) && file.successFileNum !== undefined && file.fileNum !== undefined) {
        return file.successFileNum < file.fileNum;
    }
    return false;
}

function toNumericIds(files: KnowledgeFile[]) {
    return files
        .map((file) => Number(file.id))
        .filter((id) => Number.isFinite(id));
}

export default function PortalKnowledgeWorkbench() {
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const queryClient = useQueryClient();
    const uploadInputRef = useRef<HTMLInputElement>(null);
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
    const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
    const [selectedFolderIds, setSelectedFolderIds] = useState<Set<string>>(new Set());
    const [deleteEntryIds, setDeleteEntryIds] = useState<Set<string>>(new Set());
    const [downloadEntryIds, setDownloadEntryIds] = useState<Set<string>>(new Set());
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

    const {
        data: groupedSpaces = EMPTY_GROUPED_SPACES,
        isLoading: spaceLoading,
    } = useQuery({
        queryKey: ["knowledgeSpaces", "grouped"],
        queryFn: () => getGroupedSpacesApi({ order_by: SpaceSortType.UPDATE_TIME }),
        placeholderData: (prev) => prev,
    });

    const {
        data: createOptions,
        isLoading: createOptionsLoading,
    } = useQuery({
        queryKey: ["knowledgeSpaces", "createOptions"],
        queryFn: getCreateSpaceOptionsApi,
    });

    const groups = useMemo<SpaceGroup[]>(() => {
        return [
            { key: "public", title: "公共知识库", level: SpaceLevel.PUBLIC, iconSrc: GROUP_ICON_SRC.public, spaces: groupedSpaces.publicSpaces },
            { key: "department", title: "业务域知识库", level: SpaceLevel.DEPARTMENT, iconSrc: GROUP_ICON_SRC.department, spaces: groupedSpaces.departmentSpaces },
            { key: "team", title: "团队知识库", level: SpaceLevel.TEAM, iconSrc: GROUP_ICON_SRC.team, spaces: groupedSpaces.teamSpaces },
            { key: "personal", title: "个人知识库", level: SpaceLevel.PERSONAL, iconSrc: GROUP_ICON_SRC.personal, spaces: groupedSpaces.personalSpaces },
        ];
    }, [groupedSpaces]);

    const createPermissionByLevel = useMemo<Record<SpaceLevel, boolean>>(() => ({
        [SpaceLevel.PUBLIC]: Boolean(createOptions?.canCreatePublic),
        [SpaceLevel.DEPARTMENT]: Boolean(createOptions?.canCreateDepartment),
        [SpaceLevel.TEAM]: Boolean(createOptions?.canCreateTeam),
        [SpaceLevel.PERSONAL]: Boolean(createOptions?.canCreatePersonal),
    }), [createOptions]);

    const selectableSpaces = useMemo(
        () => groups.flatMap((group) => group.spaces),
        [groups],
    );
    const spaceIds = useMemo(
        () => selectableSpaces.map((space) => space.id),
        [selectableSpaces],
    );
    const fullAccessSpaceIds = useMemo(
        () => selectableSpaces
            .filter((space) => space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN)
            .map((space) => space.id),
        [selectableSpaces],
    );
    const { permissions: spaceActionPermissions } = useKnowledgeSpaceActionPermissions(
        spaceIds,
        { fullAccessSpaceIds },
    );
    const activeGroup = useMemo(
        () => groups.find((group) => group.spaces.some((space) => space.id === activeSpace?.id)),
        [activeSpace?.id, groups],
    );

    const getSpacePermissions = useCallback((space: KnowledgeSpace) => {
        const hasFullAccess = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
        const hasPermission = (permissionId: "edit_space" | "delete_space" | "manage_space_relation") => (
            hasFullAccess || hasKnowledgeSpacePermission(spaceActionPermissions, space.id, permissionId)
        );
        return {
            canEditSpace: hasPermission("edit_space"),
            canDeleteSpace: hasPermission("delete_space"),
            canManageMembers: hasPermission("manage_space_relation"),
        };
    }, [spaceActionPermissions]);

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

    useEffect(() => {
        if (activeSpace && selectableSpaces.some((space) => space.id === activeSpace.id)) return;
        setActiveSpace(selectableSpaces[0] ?? null);
    }, [activeSpace, selectableSpaces]);

    const isActiveSpaceAdmin = activeSpace?.role === SpaceRole.CREATOR || activeSpace?.role === SpaceRole.ADMIN;
    const currentFolderNode = useMemo(
        () => currentFolderId ? findTreeNode(treeNodes, currentFolderId) : null,
        [currentFolderId, treeNodes],
    );
    const currentPath = useMemo(
        () => currentFolderId ? findTreeNodePath(treeNodes, currentFolderId) : [],
        [currentFolderId, treeNodes],
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
    }, [activeSpace?.id, showToast]);

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
    }, [activeSpace?.id, currentFolderId, loadRootTree, showToast]);

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

    useEffect(() => {
        setSelectedFile(null);
        setActivePanel(null);
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
    }, [activeSpace?.id, searchText, showToast]);

    const handleSelectFile = useCallback(
        (file: KnowledgeFile) => {
            if (file.isCreating) return;
            if (isFolder(file)) {
                setSelectedFile(null);
                setActivePanel(null);
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
    }, [activeSpace?.id, showToast]);

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
    }, [activeSpace?.id, showToast]);

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

            const newSpace = await createSpaceApi({
                name: form.name,
                description: form.description,
                auth_type: authType,
                is_released: form.publishToSquare === "yes",
                space_level: form.spaceLevel,
                department_id: form.departmentId,
                user_group_id: form.userGroupId,
                auto_tag_enabled: form.autoTagEnabled,
                auto_tag_library_id: form.autoTagLibraryId,
            });

            setActiveSpace(newSpace);
            await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
            showToast({ message: "创建知识空间成功", severity: NotificationSeverity.SUCCESS });
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

    const renderDrawer = () => {
        if (!activePanel) return null;
        const panelTitleMap: Record<PanelKey, string> = {
            details: "文档信息",
            summary: "文档摘要",
            tags: "标签管理",
            permission: "权限管理",
            share: "分享",
            ai: "AI 助手",
            features: "能力入口",
        };

        return (
            <aside className={s.drawer}>
                <div className={s.drawerHeader}>
                    <div className={s.drawerTitle}>{panelTitleMap[activePanel]}</div>
                    <button type="button" className={s.toolbarButton} onClick={() => setActivePanel(null)} aria-label="关闭">
                        <X size={14} />
                    </button>
                </div>
                <div className={s.drawerBody}>
                    {activePanel === "details" ? (
                        <div className={s.detailList}>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>知识库</span>
                                <span className={s.detailValue}>{activeSpace?.name || "-"}</span>
                            </div>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>文件名称</span>
                                <span className={s.detailValue}>{selectedFile?.name || "未选择文件"}</span>
                            </div>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>文件大小</span>
                                <span className={s.detailValue}>{selectedFile ? formatFileSize(selectedFile.size) : "-"}</span>
                            </div>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>更新时间</span>
                                <span className={s.detailValue}>{selectedFile?.updatedAt ? formatTime(selectedFile.updatedAt) : "-"}</span>
                            </div>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>路径</span>
                                <span className={s.detailValue}>{documentPath || "-"}</span>
                            </div>
                        </div>
                    ) : null}

                    {activePanel === "summary" ? (
                        <div className={s.detailList}>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>摘要内容</span>
                                <span className={s.detailValue}>{selectedFile?.summary || "暂无摘要"}</span>
                            </div>
                        </div>
                    ) : null}

                    {activePanel === "tags" ? (
                        <div>
                            {selectedFile?.tags?.length ? (
                                <div className={s.tagList}>
                                    {selectedFile.tags.map((tag) => (
                                        <span className={s.tagChip} key={`${tag.id}-${tag.name}`} title={tag.name}>
                                            {tag.name}
                                        </span>
                                    ))}
                                </div>
                            ) : (
                                <div className={s.detailValue}>暂无标签</div>
                            )}
                            <div className={s.buttonStack}>
                                <button
                                    type="button"
                                    className={s.primaryButton}
                                    disabled={!selectedFile}
                                    onClick={() => setTagModalOpen(true)}
                                >
                                    <Tags size={14} />
                                    编辑标签
                                </button>
                            </div>
                        </div>
                    ) : null}

                    {activePanel === "permission" ? (
                        <div className={s.detailList}>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>管理对象</span>
                                <span className={s.detailValue}>{selectedFile?.name || activeSpace?.name || "-"}</span>
                            </div>
                            <div className={s.buttonStack}>
                                <button
                                    type="button"
                                    className={s.primaryButton}
                                    disabled={!selectedFile}
                                    onClick={() => setPermissionOpen(true)}
                                >
                                    <ShieldCheck size={14} />
                                    打开权限管理
                                </button>
                            </div>
                        </div>
                    ) : null}

                    {activePanel === "share" ? (
                        <div className={s.detailList}>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>分享范围</span>
                                <span className={s.detailValue}>当前知识库：{activeSpace?.name || "-"}</span>
                            </div>
                            <div className={s.buttonStack}>
                                <button type="button" className={s.primaryButton} disabled={!activeSpace} onClick={copyShareLink}>
                                    <Copy size={14} />
                                    复制分享链接
                                </button>
                            </div>
                        </div>
                    ) : null}

                    {activePanel === "ai" && activeSpace ? (
                        <KnowledgeAiPanel
                            spaceId={activeSpace.id}
                            folderId={undefined}
                            contextLabel="知识空间"
                            onClose={() => setActivePanel(null)}
                        />
                    ) : null}

                    {activePanel === "features" ? (
                        <div className={s.placeholderList}>
                            {DISABLED_FEATURES.map((feature) => {
                                const Icon = feature.icon;
                                return (
                                    <button
                                        key={feature.label}
                                        type="button"
                                        className={s.placeholderItem}
                                        onClick={showUnavailable}
                                    >
                                        <span>
                                            <Icon size={14} /> {feature.label}
                                        </span>
                                        <span className={s.statusBadge}>暂未开放</span>
                                    </button>
                                );
                            })}
                        </div>
                    ) : null}
                </div>
            </aside>
        );
    };

    const renderSpaceMenu = (space: KnowledgeSpace, group: SpaceGroup) => {
        const permissions = getSpacePermissions(space);
        const showDangerAction = permissions.canDeleteSpace || Boolean(space.canUnsubscribe);
        return (
            <DropdownMenu
                onOpenChange={(open) => {
                    setSpaceMenuOpenId(open ? space.id : null);
                }}
            >
                <DropdownMenuTrigger asChild>
                    <button
                        type="button"
                        className={`${s.spaceMenuButton} ${spaceMenuOpenId === space.id ? s.spaceMenuButtonOpen : ""}`}
                        aria-label={`更多${space.name}操作`}
                        title="更多操作"
                        onClick={(event) => event.stopPropagation()}
                    >
                        <MoreHorizontal size={15} />
                    </button>
                </DropdownMenuTrigger>
                <SidebarListMoreMenuContent onClick={(event) => event.stopPropagation()}>
                    {permissions.canEditSpace ? (
                        <DropdownMenuItem
                            className={sidebarListMoreMenuItemClassName}
                            onClick={() => void handleOpenSpaceSettings(space)}
                        >
                            <Settings className={sidebarListMoreMenuIconClassName} />
                            <span className={sidebarListMoreMenuLabelClassName}>空间设置</span>
                        </DropdownMenuItem>
                    ) : null}
                    {permissions.canManageMembers ? (
                        <DropdownMenuItem
                            className={sidebarListMoreMenuItemClassName}
                            onClick={() => handleOpenSpaceMembers(space)}
                        >
                            <UsersRound className={sidebarListMoreMenuIconClassName} />
                            <span className={sidebarListMoreMenuLabelClassName}>成员管理</span>
                        </DropdownMenuItem>
                    ) : null}
                    <DropdownMenuItem
                        className={sidebarListMoreMenuItemClassName}
                        onClick={() => void handlePinSpace(space, !space.isPinned, group)}
                    >
                        {space.isPinned ? (
                            <>
                                <PinOff className={sidebarListMoreMenuIconClassName} />
                                <span className={sidebarListMoreMenuLabelClassName}>取消置顶</span>
                            </>
                        ) : (
                            <>
                                <Pin className={sidebarListMoreMenuIconClassName} />
                                <span className={sidebarListMoreMenuLabelClassName}>置顶空间</span>
                            </>
                        )}
                    </DropdownMenuItem>
                    {showDangerAction ? (
                        <>
                            <SidebarListMoreMenuDivider />
                            <DropdownMenuItem
                                className={sidebarListMoreMenuDangerItemClassName}
                                onClick={() => {
                                    if (permissions.canDeleteSpace) {
                                        void handleDeleteSpace(space);
                                        return;
                                    }
                                    void handleLeaveSpace(space);
                                }}
                            >
                                {permissions.canDeleteSpace ? (
                                    <X className={sidebarListMoreMenuDangerIconClassName} />
                                ) : (
                                    <LogOut className={sidebarListMoreMenuDangerIconClassName} />
                                )}
                                <span className={sidebarListMoreMenuDangerLabelClassName}>
                                    {permissions.canDeleteSpace ? "删除空间" : "退出空间"}
                                </span>
                            </DropdownMenuItem>
                        </>
                    ) : null}
                </SidebarListMoreMenuContent>
            </DropdownMenu>
        );
    };

    const getStatusClassName = (file: KnowledgeFile) => {
        switch (file.status) {
            case FileStatus.SUCCESS:
                return `${s.fileStatusBadge} ${s.fileStatusSuccess}`;
            case FileStatus.FAILED:
            case FileStatus.TIMEOUT:
            case FileStatus.VIOLATION:
                return `${s.fileStatusBadge} ${s.fileStatusDanger}`;
            case FileStatus.UPLOADING:
            case FileStatus.PROCESSING:
            case FileStatus.WAITING:
            case FileStatus.REBUILDING:
                return `${s.fileStatusBadge} ${s.fileStatusInfo}`;
            default:
                return s.fileStatusBadge;
        }
    };

    const renderFileRow = (file: KnowledgeFile, depth: number, node?: PortalFileTreeNode) => {
        const selected = isFolder(file) ? selectedFolderIds.has(file.id) : selectedFileIds.has(file.id);
        const active = selectedFile?.id === file.id;
        const label = statusText(file);
        const countText = isFolder(file) ? folderCountText(file) : "";
        return (
            <div
                key={file.id}
                data-testid={`file-tree-row-${file.id}`}
                className={`${s.treeRow} ${active ? s.treeRowActive : ""}`}
                style={{ paddingLeft: `${8 + depth * 18}px` }}
                title={file.name}
            >
                {isFolder(file) && node ? (
                    <button
                        type="button"
                        className={s.treeExpandButton}
                        aria-label={`${node.expanded ? "收起" : "展开"}${file.name}`}
                        onClick={() => void handleToggleFolder(node)}
                    >
                        {node.expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    </button>
                ) : (
                    <span className={s.treeExpandPlaceholder} />
                )}
                <input
                    type="checkbox"
                    className={s.treeCheckbox}
                    aria-label={`选择${file.name}`}
                    checked={selected}
                    onChange={(event) => handleToggleFileSelection(file, event.currentTarget.checked)}
                    onClick={(event) => event.stopPropagation()}
                />
                <button
                    type="button"
                    className={s.treeItemButton}
                    aria-label={`打开${file.name}`}
                    onClick={() => {
                        if (isFolder(file) && node) {
                            void handleToggleFolder(node);
                            return;
                        }
                        handleSelectFile(file);
                    }}
                >
                    {isFolder(file) ? <Folder size={14} /> : <FileText size={14} />}
                    {file.isCreating ? (
                        <input
                            autoFocus
                            className={s.createFolderInput}
                            value={folderDraft}
                            onChange={(event) => setFolderDraft(event.target.value)}
                            onClick={(event) => event.stopPropagation()}
                            onBlur={confirmCreateFolder}
                            onKeyDown={(event) => {
                                if (event.key === "Enter") confirmCreateFolder();
                                if (event.key === "Escape") fileUpload.handleCancelCreateFolder();
                            }}
                        />
                    ) : (
                        <span className={s.fileName}>{file.name}</span>
                    )}
                </button>
                {countText ? <span className={s.folderCount}>{countText}</span> : null}
                {!isFolder(file) && label ? <span className={getStatusClassName(file)}>{label}</span> : null}
            </div>
        );
    };

    const renderTreeNode = (node: PortalFileTreeNode, depth = 0): ReactNode => {
        const hasMore = node.expanded && node.loaded && node.children.length < node.total;
        return (
            <div key={node.file.id}>
                {renderFileRow(node.file, depth, node)}
                {node.expanded && node.loading ? (
                    <div className={s.treeLoadingRow} style={{ paddingLeft: `${34 + (depth + 1) * 18}px` }}>
                        加载中...
                    </div>
                ) : null}
                {node.expanded && node.children.map((child) => renderTreeNode(child, depth + 1))}
                {hasMore ? (
                    <button
                        type="button"
                        className={s.treeLoadMore}
                        style={{ marginLeft: `${34 + (depth + 1) * 18}px` }}
                        onClick={() => void handleLoadMoreChildren(node)}
                    >
                        加载更多
                    </button>
                ) : null}
            </div>
        );
    };

    const toolbarItems: Array<{
        key: PanelKey | "download" | "web" | "markdown" | "api" | "smart" | "version";
        title: string;
        icon: typeof PanelRight;
        disabled?: boolean;
        action?: () => void;
    }> = [
        { key: "details", title: "文档信息", icon: PanelRight },
        { key: "summary", title: "摘要", icon: FileText },
        { key: "permission", title: "权限", icon: LockKeyhole },
        { key: "share", title: "分享", icon: Share2 },
        { key: "ai", title: "AI 助手", icon: Bot },
        { key: "tags", title: "标签", icon: Tags },
        { key: "download", title: "下载", icon: Download, action: () => void handleDownloadSelected() },
        { key: "features", title: "更多能力", icon: Brain },
        { key: "smart", title: "智能入库", icon: Sparkles, disabled: true },
        { key: "version", title: "复杂版本管理", icon: History, disabled: true },
    ];

    return (
        <div className={s.workbench}>
            <aside className={`${s.spaceSidebar} ${spaceSidebarCollapsed ? s.spaceSidebarCollapsed : ""}`}>
                {spaceSidebarCollapsed ? (
                    <div className={s.collapsedSidebar} aria-label="知识库分组快捷栏">
                        <div className={s.collapsedGroupList}>
                            {groups.map((group) => (
                                <button
                                    key={group.key}
                                    type="button"
                                    className={s.collapsedGroupButton}
                                    title={group.title}
                                    aria-label={`打开${group.title}分组`}
                                    data-testid={`collapsed-space-group-${group.key}`}
                                    onClick={() => handleRestoreSidebar(group.key)}
                                >
                                    <img className={s.collapsedGroupIcon} src={resolveAssetUrl(group.iconSrc)} alt="" aria-hidden="true" />
                                </button>
                            ))}
                        </div>
                        <button
                            type="button"
                            className={s.collapsedExpandButton}
                            aria-label="展开知识库侧栏"
                            title="展开"
                            onClick={() => handleRestoreSidebar()}
                        >
                            <ChevronsRight size={18} />
                        </button>
                    </div>
                ) : (
                    <>
                        <div className={s.spaceHeader}>
                            <span className={s.spaceHeaderIcon}>
                                <Folder size={17} />
                            </span>
                            <span>我的知识库</span>
                            <ChevronDown size={13} style={{ marginLeft: "auto" }} />
                        </div>
                        <div className={s.spaceList}>
                            {groups.map((group) => {
                                const expanded = expandedGroups[group.key];
                                const canCreate = !createOptionsLoading && createPermissionByLevel[group.level];
                                return (
                                    <div
                                        key={group.key}
                                        data-testid={`space-group-${group.key}`}
                                        ref={(node) => {
                                            groupRefs.current[group.key] = node;
                                        }}
                                    >
                                        <div className={s.groupRow}>
                                            <button
                                                type="button"
                                                className={s.groupToggleButton}
                                                onClick={() => setExpandedGroups((prev) => ({ ...prev, [group.key]: !prev[group.key] }))}
                                            >
                                                <img
                                                    className={s.groupIcon}
                                                    src={resolveAssetUrl(group.iconSrc)}
                                                    alt=""
                                                    aria-hidden="true"
                                                    data-testid={`space-group-icon-${group.key}`}
                                                />
                                                <strong>{group.title}</strong>
                                            </button>
                                            <button
                                                type="button"
                                                className={s.groupCreateButton}
                                                aria-label={`新增${group.title}知识空间`}
                                                title={canCreate ? `新增${group.title}知识空间` : "无创建权限"}
                                                disabled={!canCreate}
                                                onClick={(event) => {
                                                    event.stopPropagation();
                                                    handleOpenCreateSpace(group);
                                                }}
                                            >
                                                <Plus size={13} />
                                            </button>
                                            <button
                                                type="button"
                                                className={s.groupExpandButton}
                                                aria-label={`${expanded ? "收起" : "展开"}${group.title}`}
                                                onClick={() => setExpandedGroups((prev) => ({ ...prev, [group.key]: !prev[group.key] }))}
                                            >
                                                {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                                            </button>
                                        </div>
                                        {expanded ? (
                                            <>
                                                {group.spaces.length ? (
                                                    group.spaces.map((space) => (
                                                        <div
                                                            key={`${group.key}-${space.id}`}
                                                            data-testid={`space-row-${space.id}`}
                                                            className={`${s.spaceRow} ${activeSpace?.id === space.id ? s.spaceRowActive : ""}`}
                                                        >
                                                            <button
                                                                type="button"
                                                                className={s.spaceSelectButton}
                                                                onClick={() => setActiveSpace(space)}
                                                            >
                                                                <FileText size={14} />
                                                                <span className={s.spaceName} title={space.name}>{space.name}</span>
                                                            </button>
                                                            <div className={s.spaceMenuArea}>
                                                                {renderSpaceMenu(space, group)}
                                                            </div>
                                                        </div>
                                                    ))
                                                ) : (
                                                    <div className={s.emptySpace}>{spaceLoading ? "加载中..." : "暂无知识库"}</div>
                                                )}
                                                {canCreate ? (
                                                    <button
                                                        type="button"
                                                        className={s.createSpaceRow}
                                                        onClick={() => handleOpenCreateSpace(group)}
                                                    >
                                                        <FolderPlus size={14} />
                                                        <span className={s.spaceName}>新建知识库</span>
                                                    </button>
                                                ) : null}
                                            </>
                                        ) : null}
                                    </div>
                                );
                            })}
                        </div>
                        <button
                            type="button"
                            className={s.sidebarFooter}
                            aria-label="收起知识库侧栏"
                            onClick={() => setSpaceSidebarCollapsed(true)}
                        >
                            <ChevronsLeft size={14} />
                            <span>收起</span>
                        </button>
                    </>
                )}
            </aside>

            <aside className={s.filePane}>
                <div className={s.filePaneHeader}>
                    <div className={s.sectionTitle} data-testid="active-space-title">{activeSpace?.name || "我的技术文档"}</div>
                    <div className={s.searchBox}>
                        <Search size={14} />
                        <input
                            className={s.searchInput}
                            value={searchText}
                            placeholder="搜索文件..."
                            onChange={(event) => {
                                const nextValue = event.target.value;
                                setSearchText(nextValue);
                                if (!nextValue.trim()) {
                                    setSearchMode(false);
                                    setSearchResults([]);
                                    setSelectedFileIds(new Set());
                                    setSelectedFolderIds(new Set());
                                }
                            }}
                            onKeyDown={(event) => {
                                if (event.key === "Enter") void handleSearch();
                            }}
                        />
                    </div>
                    <div className={s.fileActions}>
                        {selectedCount > 0 ? (
                            <>
                                <span className={s.selectionCount}>已选择 {selectedCount} 项</span>
                                <button type="button" className={s.folderAction} onClick={clearBatchSelection} title="取消选择" aria-label="取消选择">
                                    <X size={14} />
                                </button>
                                <button type="button" className={s.folderAction} onClick={() => void handleBatchDownload()} disabled={!selectedDownloadable} title="批量下载" aria-label="批量下载">
                                    <Download size={14} />
                                </button>
                                <button type="button" className={s.folderAction} onClick={() => void handleBatchRetry()} disabled={!canBatchRetry} title="批量重试" aria-label="批量重试">
                                    <History size={14} />
                                </button>
                                <button type="button" className={s.folderAction} onClick={() => void handleBatchDelete()} disabled={!selectedDeletable} title="批量删除" aria-label="批量删除">
                                    <X size={14} />
                                </button>
                            </>
                        ) : (
                            <>
                                <button type="button" className={s.folderAction} onClick={() => uploadInputRef.current?.click()} disabled={!activeSpace || !canUploadFile} title={canUploadFile ? "上传文件" : "无上传权限"}>
                                    <Upload size={14} />
                                </button>
                                <button type="button" className={s.folderAction} onClick={() => fileUpload.handleCreateFolder()} disabled={!activeSpace || searchMode || !canCreateFolder} title={canCreateFolder ? "新建文件夹" : "无创建权限"}>
                                    <Folder size={14} />
                                </button>
                                <button type="button" className={s.folderAction} onClick={showUnavailable} title="导入网页">
                                    <Globe2 size={14} />
                                </button>
                                <button type="button" className={s.folderAction} onClick={showUnavailable} title="API 导入">
                                    <Import size={14} />
                                </button>
                            </>
                        )}
                    </div>
                    <input
                        ref={uploadInputRef}
                        type="file"
                        multiple
                        hidden
                        onChange={(event) => {
                            void fileUpload.handleUploadFile(event.currentTarget.files || undefined);
                            event.currentTarget.value = "";
                        }}
                    />
                </div>

                <div className={s.fileList}>
                    {!activeSpace ? (
                        <div className={s.stateBox}>
                            <div className={s.stateTitle}>暂无可用知识库</div>
                            <div>请先在 BiSheng 中创建或加入知识库。</div>
                        </div>
                    ) : treeLoading && visibleTreeNodes.length === 0 ? (
                        <div className={s.stateBox}>正在加载文件...</div>
                    ) : searchLoading ? (
                        <div className={s.stateBox}>正在搜索文件...</div>
                    ) : searchMode ? (
                        searchResults.length === 0 ? (
                            <div className={s.stateBox}>暂无匹配文件</div>
                        ) : (
                            <>
                                <div className={s.searchResultTitle}>搜索结果</div>
                                {searchResults.map((file) => renderFileRow(file, 0))}
                            </>
                        )
                    ) : visibleTreeNodes.length === 0 ? (
                        <div className={s.stateBox}>暂无文件</div>
                    ) : (
                        <>
                            {visibleTreeNodes.map((node) => renderTreeNode(node))}
                            {treeNodes.length < treeRootTotal ? (
                                <button
                                    type="button"
                                    className={s.treeLoadMore}
                                    disabled={treeRootLoadingMore}
                                    onClick={() => void loadRootTree(treeRootPage + 1, true)}
                                >
                                    {treeRootLoadingMore ? "加载中..." : "加载更多"}
                                </button>
                            ) : null}
                        </>
                    )}
                </div>
            </aside>

            <main className={s.documentArea}>
                <section className={s.documentShell}>
                    {selectedFile ? (
                        <>
                            <div className={s.documentHeader}>
                                <div className={s.docIcon}>
                                    <FileText size={30} />
                                </div>
                                <div className={s.docTitleBlock}>
                                    <h1 className={s.docTitle}>{selectedFile.name}</h1>
                                    <div className={s.docPath}>{documentPath}</div>
                                </div>
                                <div className={s.docActions}>
                                    <button type="button" className={s.iconAction} title="权限" onClick={() => setActivePanel("permission")}>
                                        <ShieldCheck size={16} />
                                    </button>
                                    <button type="button" className={s.iconAction} title="分享" onClick={() => setActivePanel("share")}>
                                        <Share2 size={16} />
                                    </button>
                                    <button type="button" className={s.iconAction} title="下载" onClick={() => void handleDownloadSelected()}>
                                        <Download size={16} />
                                    </button>
                                    <button type="button" className={s.iconAction} title="AI" onClick={() => setActivePanel("ai")}>
                                        <Bot size={16} />
                                    </button>
                                    <button type="button" className={s.iconAction} title="标签" onClick={() => setActivePanel("tags")}>
                                        <Tags size={16} />
                                    </button>
                                </div>
                            </div>
                            <div className={s.divider} />
                            <div className={s.summaryBar}>
                                <div className={s.summaryTitle}>
                                    <FileText size={16} />
                                    文档摘要
                                </div>
                                <div className={s.summaryText}>{selectedFile.summary || "暂无摘要"}</div>
                                <button type="button" className={s.summaryButton} disabled title="摘要为只读展示">
                                    保存摘要
                                </button>
                                <ChevronDown size={14} />
                            </div>
                            <div className={s.previewHost}>
                                {preview.loading ? (
                                    <div className={s.stateBox}>正在加载预览...</div>
                                ) : preview.error ? (
                                    <div className={s.stateBox}>
                                        <div className={s.stateTitle}>无法预览</div>
                                        <div>{preview.error}</div>
                                    </div>
                                ) : preview.fileUrl ? (
                                    <div className={s.previewFrame}>
                                        <FilePreview
                                            fileName={selectedFile.name}
                                            fileType={preview.fileType}
                                            fileUrl={preview.fileUrl}
                                            compactMode
                                            allowDownload={false}
                                        />
                                    </div>
                                ) : (
                                    <div className={s.previewCard}>
                                        <h2 className={s.docContentTitle}>{selectedFile.name.replace(/\.[^.]+$/, "")}</h2>
                                        <h3 className={s.docSectionTitle}>文档概述</h3>
                                        <p>当前文档已选中，正在等待预览内容。</p>
                                    </div>
                                )}
                            </div>
                        </>
                    ) : (
                        <div className={`${s.stateBox} ${s.documentEmptyState}`}>
                            <FileText size={42} />
                            <div className={s.stateTitle}>请选择一个文件</div>
                            <div>点击左侧文件后，将在这里展示摘要、预览和操作入口。</div>
                        </div>
                    )}
                </section>

                {renderDrawer()}

                <aside className={s.toolRail}>
                    {toolbarItems.map((item) => {
                        const Icon = item.icon;
                        const isPanel = item.key !== "download" && item.key !== "smart" && item.key !== "version";
                        const disabledByContext = !item.disabled && !activeSpace && item.key !== "features";
                        return (
                            <button
                                type="button"
                                key={item.key}
                                className={`${s.toolbarButton} ${activePanel === item.key ? s.toolbarButtonActive : ""}`}
                                title={item.title}
                                aria-disabled={item.disabled || disabledByContext}
                                disabled={disabledByContext}
                                onClick={() => {
                                    if (item.disabled) {
                                        showUnavailable();
                                        return;
                                    }
                                    if (item.action) {
                                        item.action();
                                        return;
                                    }
                                    if (isPanel) {
                                        setActivePanel(item.key as PanelKey);
                                    }
                                }}
                            >
                                <Icon size={16} />
                            </button>
                        );
                    })}
                    <button type="button" className={s.toolbarButton} title="外部链接" onClick={showUnavailable}>
                        <Link2 size={16} />
                    </button>
                </aside>
            </main>

            {activeSpace && selectedFile ? (
                <EditTagsModal
                    isOpen={tagModalOpen}
                    onClose={() => setTagModalOpen(false)}
                    onSaved={() => {
                        setTagModalOpen(false);
                        void loadRootTree(1);
                    }}
                    spaceId={activeSpace.id}
                    fileId={selectedFile.id}
                    initialTagIds={selectedFile.tags.map((tag) => tag.id).filter((id) => id >= 0)}
                />
            ) : null}

            {activeSpace && selectedFile ? (
                <KnowledgeSpaceShareDialog
                    open={permissionOpen}
                    onOpenChange={setPermissionOpen}
                    resourceType="knowledge_file"
                    resourceId={selectedFile.id}
                    resourceName={selectedFile.name}
                    currentUserRole={activeSpace.role}
                    showShareTab={false}
                    showPermissionTab
                />
            ) : null}

            {spacePermissionDialogSpace ? (
                <KnowledgeSpaceShareDialog
                    open={spacePermissionOpen}
                    onOpenChange={setSpacePermissionOpen}
                    resourceId={spacePermissionDialogSpace.id}
                    resourceName={spacePermissionDialogSpace.name}
                    currentUserRole={spacePermissionDialogSpace.role}
                    spaceLevel={spacePermissionDialogSpace.spaceLevel}
                    showShareTab={false}
                    showMembersTab={false}
                    showPermissionTab
                    onPermissionChanged={handleSpacePermissionChanged}
                />
            ) : null}

            <CreateKnowledgeSpaceDrawer
                open={createDrawerOpen}
                onOpenChange={(open) => {
                    setCreateDrawerOpen(open);
                    if (!open) setEditingSpace(null);
                }}
                onConfirm={handleConfirmCreateSpace}
                mode={editingSpace ? "edit" : "create"}
                editingSpace={editingSpace}
                initialSpaceLevel={pendingCreateLevel}
                onViewSpace={() => setCreateDrawerOpen(false)}
                onManageMembers={() => {
                    setCreateDrawerOpen(false);
                    if (editingSpace) handleOpenSpaceMembers(editingSpace);
                }}
            />

            <Dialog
                open={fileUpload.duplicateFiles.length > 0}
                onOpenChange={(open) => !open && fileUpload.handleDuplicateSkip()}
            >
                <DialogContent className="sm:max-w-[460px]" onPointerDownOutside={(event) => event.preventDefault()}>
                    <DialogHeader>
                        <DialogTitle>发现重名文件</DialogTitle>
                    </DialogHeader>
                    <ul className={s.dialogList}>
                        {fileUpload.duplicateFiles.map((entry) => (
                            <li key={entry.fileId} className={s.dialogListItem}>
                                {entry.fileName}
                                {entry.oldFileLevelPath ? `（${entry.oldFileLevelPath}）` : ""}
                            </li>
                        ))}
                    </ul>
                    <DialogFooter>
                        <Button variant="outline" className="h-8" onClick={fileUpload.handleDuplicateSkip}>
                            取消
                        </Button>
                        <Button className="h-8" onClick={fileUpload.handleDuplicateOverwrite}>
                            覆盖
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
