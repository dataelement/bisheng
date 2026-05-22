import { useCallback, useEffect, useMemo, useRef, useState, type ComponentProps, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
    Bot,
    BriefcaseBusiness,
    ChevronDown,
    ChevronRight,
    ChevronsLeft,
    ChevronsRight,
    Clock,
    Copy,
    Download,
    FileText,
    Folder,
    FolderPlus,
    FunnelIcon,
    Globe2,
    History,
    ListChecks,
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
    Share2,
    ShieldCheck,
    SquarePen,
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
    addFilesApi,
    batchDeleteApi,
    batchDownloadApi,
    batchRetryApi,
    createFolderApi,
    createSpaceApi,
    deleteSpaceApi,
    getFileDownloadApi,
    getFilePreviewApi,
    getCreateSpaceOptionsApi,
    getGroupedSpacesApi,
    getSimilarCandidatesApi,
    getSpaceChildrenApi,
    getSpaceInfoApi,
    linkAsNewVersionApi,
    listKnowledgeFolders,
    fileStatusToNumber,
    pinSpaceApi,
    searchSpaceChildrenApi,
    uploadFileToServerApi,
    type SimilarCandidateEntry,
    unsubscribeSpaceApi,
    updateSpaceApi,
} from "~/api/knowledge";
import { checkPermission } from "~/api/permission";
import { NotificationSeverity } from "~/common";
import { useConfirm, useToastContext } from "~/Providers";
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
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
import LegacyFileIcon from "~/components/ui/icon/File";
import FilePreview from "../FilePreview";
import { CreateKnowledgeSpaceDrawer, type CreateKnowledgeSpaceFormData } from "../CreateKnowledgeSpaceDrawer";
import { EditTagsModal } from "../SpaceDetail/EditTagsModal";
import { KnowledgeSpaceShareDialog } from "../SpaceDetail/KnowledgeSpaceShareDialog";
import { AiAssistantPanel } from "~/pages/Subscription/AiChat/AiAssistantPanel";
import {
    hasKnowledgeSpacePermission,
    useKnowledgeSpaceActionPermissions,
} from "../hooks/useKnowledgeSpacePermissions";
import { useFileUpload } from "../hooks/useFileUpload";
import {
    ALLOWED_EXTENSIONS,
    DEFAULT_MAX_FILE_SIZE_MB,
    MAX_FOLDER_UPLOAD_COUNT,
    filterFolderUploadFiles,
    formatTime,
    getRootFolderName,
    isHiddenName,
    triggerUrlDownload,
} from "../knowledgeUtils";
import s from "./PortalKnowledgeWorkbench.module.css";

type SpaceGroupKey = "public" | "department" | "team" | "personal";
type PanelKey = "properties" | "time" | "source" | "usage" | "share";
type PortalToolRailKey = "toggle" | "properties" | "time" | "source" | "usage" | "permission";

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

type PortalUploadStep = "select" | "review";

interface PortalUploadFileItem {
    id: string;
    file: File;
    source: "file" | "folder";
}

interface PortalUploadFolderNode {
    id: string;
    name: string;
    children: PortalUploadFolderNode[];
    expanded: boolean;
    loaded: boolean;
    loading: boolean;
}

interface PortalUploadReviewRow {
    file: KnowledgeFile;
    selected: boolean;
    recommendedFolderId: string | null;
    recommendedFolderName: string;
    storageFolderId: string | null;
    storageFolderName: string;
    candidates: SimilarCandidateEntry[];
    candidatesLoading: boolean;
    candidateError: boolean;
    selectedTargetDocumentId: number | null;
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

const STATUS_FILTER_OPTIONS: Array<{ status: FileStatus; label: string }> = [
    { status: FileStatus.UPLOADING, label: "上传中" },
    { status: FileStatus.WAITING, label: "排队中" },
    { status: FileStatus.PROCESSING, label: "解析中" },
    { status: FileStatus.REBUILDING, label: "重建中" },
    { status: FileStatus.SUCCESS, label: "成功" },
    { status: FileStatus.FAILED, label: "失败" },
    { status: FileStatus.VIOLATION, label: "违规" },
    { status: FileStatus.TIMEOUT, label: "超时" },
];

type LegacyFileIconType = ComponentProps<typeof LegacyFileIcon>["type"];

const LEGACY_FILE_ICON_TYPE_BY_EXTENSION: Record<string, LegacyFileIconType | "xlsx"> = {
    md: "md",
    txt: "txt",
    html: "html",
    csv: "csv",
    xls: "csv",
    xlsx: "xlsx",
    pdf: "pdf",
    doc: "doc",
    docx: "docx",
};

function isFolder(file: KnowledgeFile) {
    return file.type === FileType.FOLDER;
}

function getPortalFileIconType(file: KnowledgeFile): LegacyFileIconType | "xlsx" {
    if (isFolder(file)) return "dir";
    const parts = file.name.split(".");
    const extension = parts.length > 1 ? parts.pop()?.toLowerCase() || "" : "";
    return LEGACY_FILE_ICON_TYPE_BY_EXTENSION[extension] || "txt";
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

function createUploadFolderNode(item: { id: number | string; file_name?: string; name?: string }): PortalUploadFolderNode {
    return {
        id: String(item.id),
        name: String(item.file_name ?? item.name ?? ""),
        children: [],
        expanded: false,
        loaded: false,
        loading: false,
    };
}

function updateUploadFolderNode(
    nodes: PortalUploadFolderNode[],
    folderId: string,
    updater: (node: PortalUploadFolderNode) => PortalUploadFolderNode,
): PortalUploadFolderNode[] {
    return nodes.map((node) => {
        if (node.id === folderId) return updater(node);
        if (!node.children.length) return node;
        return {
            ...node,
            children: updateUploadFolderNode(node.children, folderId, updater),
        };
    });
}

function flattenUploadFolders(nodes: PortalUploadFolderNode[]): Array<{ id: string; name: string }> {
    return nodes.flatMap((node) => [
        { id: node.id, name: node.name },
        ...flattenUploadFolders(node.children),
    ]);
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

function toStatusNumbers(statuses: FileStatus[]) {
    return statuses
        .map(fileStatusToNumber)
        .filter((status) => Number.isFinite(status));
}

export default function PortalKnowledgeWorkbench() {
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const queryClient = useQueryClient();
    const uploadInputRef = useRef<HTMLInputElement>(null);
    const uploadFolderInputRef = useRef<HTMLInputElement>(null);
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
    const [canCreateFolder, setCanCreateFolder] = useState(false);
    const [canUploadFile, setCanUploadFile] = useState(false);
    const [currentFolderId, setCurrentFolderId] = useState<string | undefined>();
    const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
    const [uploadStep, setUploadStep] = useState<PortalUploadStep>("select");
    const [uploadFiles, setUploadFiles] = useState<PortalUploadFileItem[]>([]);
    const [uploadLocalFolderName, setUploadLocalFolderName] = useState<string | null>(null);
    const [uploadFolderId, setUploadFolderId] = useState<string | null>(null);
    const [uploadFolderName, setUploadFolderName] = useState("根目录");
    const [uploadFolderNodes, setUploadFolderNodes] = useState<PortalUploadFolderNode[]>([]);
    const [uploadFolderLoading, setUploadFolderLoading] = useState(false);
    const [uploadSubmitting, setUploadSubmitting] = useState(false);
    const [uploadImporting, setUploadImporting] = useState(false);
    const [uploadReviewRows, setUploadReviewRows] = useState<PortalUploadReviewRow[]>([]);
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

    const uploadFolderOptions = useMemo(
        () => {
            const folders = flattenUploadFolders(uploadFolderNodes);
            const options: Array<{ id: string | null; name: string }> = [{ id: null, name: "根目录" }];
            const seen = new Set([""]);
            const appendOption = (id: string | null, name: string) => {
                const key = id ?? "";
                if (seen.has(key)) return;
                seen.add(key);
                options.push({ id, name });
            };
            if (uploadFolderId !== null) {
                appendOption(uploadFolderId, uploadFolderName);
            }
            uploadReviewRows.forEach((row) => {
                if (row.recommendedFolderId !== null) {
                    appendOption(row.recommendedFolderId, row.recommendedFolderName);
                }
                if (row.storageFolderId !== null) {
                    appendOption(row.storageFolderId, row.storageFolderName);
                }
            });
            folders.forEach((folder) => appendOption(folder.id, folder.name));
            return options;
        },
        [uploadFolderId, uploadFolderName, uploadFolderNodes, uploadReviewRows],
    );

    const resetUploadDialog = useCallback(() => {
        setUploadDialogOpen(false);
        setUploadStep("select");
        setUploadFiles([]);
        setUploadLocalFolderName(null);
        setUploadFolderId(null);
        setUploadFolderName("根目录");
        setUploadFolderNodes([]);
        setUploadFolderLoading(false);
        setUploadSubmitting(false);
        setUploadImporting(false);
        setUploadReviewRows([]);
        if (uploadInputRef.current) {
            uploadInputRef.current.value = "";
        }
        if (uploadFolderInputRef.current) {
            uploadFolderInputRef.current.value = "";
        }
    }, []);

    const handleOpenUploadDialog = useCallback(() => {
        if (!uploadTargetSpace || !canUploadInPortal) return;
        if (!activeSpace) {
            setActiveSpace(uploadTargetSpace);
        }
        const currentFolderName = currentFolderId
            ? currentPath[currentPath.length - 1]?.name || currentFolderNode?.file.name || "根目录"
            : "根目录";
        setUploadStep("select");
        setUploadFiles([]);
        setUploadLocalFolderName(null);
        setUploadReviewRows([]);
        setUploadFolderId(currentFolderId ?? null);
        setUploadFolderName(currentFolderName);
        setUploadDialogOpen(true);
    }, [activeSpace, canUploadInPortal, currentFolderId, currentFolderNode?.file.name, currentPath, uploadTargetSpace]);

    useEffect(() => {
        if (!uploadDialogOpen || !activeSpace) return;
        let cancelled = false;
        setUploadFolderLoading(true);
        listKnowledgeFolders({
            space_id: activeSpace.id,
            parent_id: null,
            file_status: statusFilterNumbers,
        })
            .then(({ items }) => {
                if (cancelled) return;
                setUploadFolderNodes(items.map(createUploadFolderNode));
            })
            .catch(() => {
                if (cancelled) return;
                setUploadFolderNodes([]);
                showToast({ message: "目录加载失败", severity: NotificationSeverity.ERROR });
            })
            .finally(() => {
                if (!cancelled) setUploadFolderLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [activeSpace, showToast, statusFilterNumbers, uploadDialogOpen]);

    const handleAddUploadFiles = useCallback((files?: FileList | File[]) => {
        const nextFiles = Array.from(files ?? []);
        if (!nextFiles.length) return;
        setUploadLocalFolderName(null);
        setUploadFiles((prev) => [
            ...prev.filter((item) => item.source === "file"),
            ...nextFiles.map((file) => ({
                id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
                file,
                source: "file" as const,
            })),
        ]);
        setUploadStep("select");
        setUploadReviewRows([]);
    }, []);

    const handleAddUploadFolder = useCallback((files?: FileList | File[]) => {
        const allFiles = Array.from(files ?? []);
        if (!allFiles.length) return;

        const rootNames = Array.from(new Set(
            allFiles
                .map((file) => getRootFolderName(file.webkitRelativePath || ""))
                .filter(Boolean),
        ));
        const rootName = rootNames[0] || "";
        if (!rootName) {
            showToast({ message: "请选择一个有效文件夹", severity: NotificationSeverity.WARNING });
            return;
        }
        if (isHiddenName(rootName)) {
            showToast({ message: "不支持上传隐藏文件夹", severity: NotificationSeverity.WARNING });
            return;
        }
        if (allFiles.length > MAX_FOLDER_UPLOAD_COUNT) {
            showToast({
                message: `文件夹上传最多支持 ${MAX_FOLDER_UPLOAD_COUNT} 个文件`,
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        if (rootNames.length > 1) {
            showToast({ message: "一次仅支持上传一个文件夹，已保留第一个文件夹", severity: NotificationSeverity.INFO });
        }

        const filesInRoot = allFiles.filter((file) => getRootFolderName(file.webkitRelativePath || "") === rootName);
        const validFiles = filterFolderUploadFiles(filesInRoot, {
            allowedExtensions: ALLOWED_EXTENSIONS,
            maxSizeMB: DEFAULT_MAX_FILE_SIZE_MB,
        });
        if (!validFiles.length) {
            showToast({ message: "文件夹根目录下没有可上传的支持文件", severity: NotificationSeverity.WARNING });
            return;
        }

        setUploadLocalFolderName(rootName);
        setUploadFiles(validFiles.map((file) => ({
            id: `${rootName}-${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
            file,
            source: "folder" as const,
        })));
        setUploadStep("select");
        setUploadReviewRows([]);
    }, [showToast]);

    const handleRemoveUploadFile = useCallback((fileId: string) => {
        setUploadFiles((prev) => {
            const next = prev.filter((item) => item.id !== fileId);
            if (!next.length) {
                setUploadLocalFolderName(null);
            }
            return next;
        });
        setUploadReviewRows([]);
    }, []);

    const handleSelectUploadFolder = useCallback((folderId: string | null, folderName: string) => {
        setUploadFolderId(folderId);
        setUploadFolderName(folderName);
    }, []);

    const handleToggleUploadFolder = useCallback(async (node: PortalUploadFolderNode) => {
        const spaceId = activeSpace?.id;
        if (!spaceId) return;
        if (node.expanded) {
            setUploadFolderNodes((prev) => updateUploadFolderNode(prev, node.id, (item) => ({
                ...item,
                expanded: false,
            })));
            return;
        }
        if (node.loaded) {
            setUploadFolderNodes((prev) => updateUploadFolderNode(prev, node.id, (item) => ({
                ...item,
                expanded: true,
            })));
            return;
        }
        setUploadFolderNodes((prev) => updateUploadFolderNode(prev, node.id, (item) => ({
            ...item,
            expanded: true,
            loading: true,
        })));
        const parentId = Number(node.id);
        try {
            const { items } = await listKnowledgeFolders({
                space_id: spaceId,
                parent_id: Number.isFinite(parentId) ? parentId : node.id,
                file_status: statusFilterNumbers,
            });
            setUploadFolderNodes((prev) => updateUploadFolderNode(prev, node.id, (item) => ({
                ...item,
                children: items.map(createUploadFolderNode),
                expanded: true,
                loaded: true,
                loading: false,
            })));
        } catch {
            setUploadFolderNodes((prev) => updateUploadFolderNode(prev, node.id, (item) => ({
                ...item,
                expanded: false,
                loading: false,
            })));
            showToast({ message: "目录加载失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, showToast, statusFilterNumbers]);

    const loadUploadReviewCandidates = useCallback((rows: PortalUploadReviewRow[]) => {
        rows.forEach((row) => {
            const fileId = Number(row.file.id);
            if (!Number.isFinite(fileId)) return;
            void getSimilarCandidatesApi(fileId)
                .then((candidates) => {
                    setUploadReviewRows((prev) => prev.map((item) => item.file.id === row.file.id ? {
                        ...item,
                        candidates,
                        candidatesLoading: false,
                        candidateError: false,
                    } : item));
                })
                .catch(() => {
                    setUploadReviewRows((prev) => prev.map((item) => item.file.id === row.file.id ? {
                        ...item,
                        candidates: [],
                        candidatesLoading: false,
                        candidateError: true,
                    } : item));
                    showToast({ message: `${row.file.name} 版本推荐加载失败`, severity: NotificationSeverity.ERROR });
                });
        });
    }, [showToast]);

    const handleUploadNext = useCallback(async () => {
        if (uploadReviewRows.length) {
            setUploadStep("review");
            return;
        }
        if (!activeSpace) return;
        if (!uploadFiles.length) {
            showToast({ message: "请先选择文件", severity: NotificationSeverity.INFO });
            return;
        }
        setUploadSubmitting(true);
        try {
            if (uploadLocalFolderName) {
                const targetParentId = uploadFolderId === null ? null : Number(uploadFolderId);
                const normalizedParentId = uploadFolderId === null
                    ? null
                    : Number.isFinite(targetParentId)
                        ? targetParentId
                        : uploadFolderId;
                const { items } = await listKnowledgeFolders({
                    space_id: activeSpace.id,
                    parent_id: normalizedParentId,
                });
                if (items.some((item) => item.file_name === uploadLocalFolderName)) {
                    showToast({
                        message: `该位置已存在同名文件夹「${uploadLocalFolderName}」`,
                        severity: NotificationSeverity.WARNING,
                    });
                    return;
                }

                const createdFolder = await createFolderApi(activeSpace.id, {
                    name: uploadLocalFolderName,
                    parent_id: uploadFolderId,
                });
                const createdFolderId = Number(createdFolder.id);
                if (!Number.isFinite(createdFolderId)) {
                    throw new Error("创建文件夹失败");
                }

                const uploadResults = await Promise.all(
                    uploadFiles.map((item) => uploadFileToServerApi(activeSpace.id, item.file, item.file.name)),
                );
                const filePaths = uploadResults.map((item) => item.file_path);
                const registeredFiles = await addFilesApi(activeSpace.id, {
                    file_path: filePaths,
                    parent_id: createdFolderId,
                });
                const createdFolderOptionId = String(createdFolder.id);
                const rows: PortalUploadReviewRow[] = registeredFiles.map((file) => ({
                    file,
                    selected: true,
                    recommendedFolderId: createdFolderOptionId,
                    recommendedFolderName: createdFolder.name,
                    storageFolderId: createdFolderOptionId,
                    storageFolderName: createdFolder.name,
                    candidates: [],
                    candidatesLoading: true,
                    candidateError: false,
                    selectedTargetDocumentId: null,
                }));
                setUploadReviewRows(rows);
                setUploadStep("review");
                loadUploadReviewCandidates(rows);
                return;
            }

            const uploadResults = await Promise.all(
                uploadFiles.map((item) => uploadFileToServerApi(activeSpace.id, item.file)),
            );
            const filePaths = uploadResults.map((item) => item.file_path);
            const parentId = uploadFolderId === null ? null : Number(uploadFolderId);
            const registeredFiles = await addFilesApi(activeSpace.id, {
                file_path: filePaths,
                parent_id: parentId !== null && Number.isFinite(parentId) ? parentId : null,
            });
            const rows: PortalUploadReviewRow[] = registeredFiles.map((file) => ({
                file,
                selected: true,
                recommendedFolderId: uploadFolderId,
                recommendedFolderName: uploadFolderName,
                storageFolderId: uploadFolderId,
                storageFolderName: uploadFolderName,
                candidates: [],
                candidatesLoading: true,
                candidateError: false,
                selectedTargetDocumentId: null,
            }));
            setUploadReviewRows(rows);
            setUploadStep("review");
            loadUploadReviewCandidates(rows);
        } catch (error) {
            const message = error instanceof Error && error.message ? error.message : "上传失败";
            showToast({ message, severity: NotificationSeverity.ERROR });
        } finally {
            setUploadSubmitting(false);
        }
    }, [activeSpace, loadUploadReviewCandidates, showToast, statusFilterNumbers, uploadFiles, uploadFolderId, uploadFolderName, uploadLocalFolderName, uploadReviewRows.length]);

    const handleStartUploadImport = useCallback(async () => {
        const rows = uploadReviewRows.filter((row) => row.selected);
        if (!rows.length) {
            showToast({ message: "请至少选择一个文件", severity: NotificationSeverity.INFO });
            return;
        }
        setUploadImporting(true);
        try {
            for (const row of rows) {
                if (!row.selectedTargetDocumentId) continue;
                const fileId = Number(row.file.id);
                if (!Number.isFinite(fileId)) continue;
                await linkAsNewVersionApi({
                    knowledge_file_id: fileId,
                    target_document_id: row.selectedTargetDocumentId,
                });
            }
            await reloadFiles();
            resetUploadDialog();
            showToast({ message: "导入成功", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "版本关联失败", severity: NotificationSeverity.ERROR });
        } finally {
            setUploadImporting(false);
        }
    }, [reloadFiles, resetUploadDialog, showToast, uploadReviewRows]);

    const documentPath = useMemo(() => {
        const names = [
            "全部知识库",
            activeGroup?.title,
            activeSpace?.name,
            selectedFile?.path || selectedFile?.name,
        ].filter(Boolean);
        return names.join("/");
    }, [activeGroup?.title, activeSpace?.name, selectedFile?.name, selectedFile?.path]);

    const renderUploadFolderNode = (node: PortalUploadFolderNode, depth = 0): ReactNode => (
        <div key={node.id}>
            <div className={s.uploadFolderRow} style={{ paddingLeft: `${8 + depth * 16}px` }}>
                <button
                    type="button"
                    className={s.uploadFolderExpandButton}
                    aria-label={`${node.expanded ? "收起" : "展开"}上传目录${node.name}`}
                    onClick={() => void handleToggleUploadFolder(node)}
                >
                    {node.expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                </button>
                <button
                    type="button"
                    className={`${s.uploadFolderSelectButton} ${uploadFolderId === node.id ? s.uploadFolderSelectButtonActive : ""}`}
                    aria-label={`选择上传目录${node.name}`}
                    onClick={() => handleSelectUploadFolder(node.id, node.name)}
                >
                    <Folder size={14} />
                    <span>{node.name}</span>
                </button>
            </div>
            {node.expanded && node.loading ? (
                <div className={s.uploadFolderLoading} style={{ paddingLeft: `${30 + (depth + 1) * 16}px` }}>
                    加载中...
                </div>
            ) : null}
            {node.expanded ? node.children.map((child) => renderUploadFolderNode(child, depth + 1)) : null}
        </div>
    );

    const renderUploadDialog = () => {
        const selectedReviewCount = uploadReviewRows.filter((row) => row.selected).length;
        return (
            <Dialog
                open={uploadDialogOpen}
                onOpenChange={(open) => {
                    if (!open) {
                        resetUploadDialog();
                    } else {
                        setUploadDialogOpen(true);
                    }
                }}
            >
                {uploadStep === "select" ? (
                    <DialogContent className={s.uploadDialogContent} onPointerDownOutside={(event) => event.preventDefault()}>
                        <div data-testid="portal-upload-dialog" className={s.uploadDialogInner}>
                            <DialogHeader>
                                <DialogTitle>上传文件</DialogTitle>
                            </DialogHeader>
                            <div className={s.uploadStepBody}>
                            <div className={s.uploadSection}>
                                <div className={s.uploadLabel}>选择文件</div>
                                <div
                                    className={s.uploadDropzone}
                                    onDragOver={(event) => {
                                        event.preventDefault();
                                    }}
                                    onDrop={(event) => {
                                        event.preventDefault();
                                        handleAddUploadFiles(event.dataTransfer.files);
                                    }}
                                >
                                    <Upload size={34} />
                                    <span>点击选择文件或拖拽文件到此处</span>
                                    <small>支持多个文件同时上传</small>
                                    <div className={s.uploadPickActions}>
                                        <button
                                            type="button"
                                            className={s.uploadPickButton}
                                            onClick={() => uploadInputRef.current?.click()}
                                        >
                                            选择文件
                                        </button>
                                        <button
                                            type="button"
                                            className={s.uploadPickButton}
                                            onClick={() => uploadFolderInputRef.current?.click()}
                                        >
                                            选择文件夹
                                        </button>
                                    </div>
                                </div>
                                <input
                                    ref={uploadInputRef}
                                    aria-label="选择文件"
                                    className={s.uploadNativeInput}
                                    type="file"
                                    multiple
                                    onChange={(event) => {
                                        handleAddUploadFiles(event.currentTarget.files || undefined);
                                        event.currentTarget.value = "";
                                    }}
                                />
                                <input
                                    ref={uploadFolderInputRef}
                                    aria-label="选择文件夹"
                                    className={s.uploadNativeInput}
                                    type="file"
                                    multiple
                                    onChange={(event) => {
                                        handleAddUploadFolder(event.currentTarget.files || undefined);
                                        event.currentTarget.value = "";
                                    }}
                                    {...({ webkitdirectory: "", directory: "" } as any)}
                                />
                            </div>

                            <div className={s.uploadSection}>
                                <div className={s.uploadLabel}>上传位置</div>
                                <label className={s.uploadField}>
                                    <span>目标知识库</span>
                                    <input aria-label="目标知识库" className={s.uploadReadonlyInput} value={activeSpace?.name || ""} readOnly />
                                </label>
                                <div className={s.uploadField}>
                                    <span>上传目标目录</span>
                                    <div className={s.uploadFolderPicker}>
                                        <div className={s.uploadFolderSelected} data-testid="selected-upload-folder">
                                            {uploadFolderName}
                                        </div>
                                        <div className={s.uploadFolderTree}>
                                            <div className={s.uploadFolderRow}>
                                                <span className={s.uploadFolderExpandPlaceholder} />
                                                <button
                                                    type="button"
                                                    className={`${s.uploadFolderSelectButton} ${uploadFolderId === null ? s.uploadFolderSelectButtonActive : ""}`}
                                                    aria-label="选择上传目录根目录"
                                                    onClick={() => handleSelectUploadFolder(null, "根目录")}
                                                >
                                                    <Folder size={14} />
                                                    <span>选择根目录</span>
                                                </button>
                                            </div>
                                            {uploadFolderLoading ? (
                                                <div className={s.uploadFolderLoading}>目录加载中...</div>
                                            ) : uploadFolderNodes.length ? (
                                                uploadFolderNodes.map((node) => renderUploadFolderNode(node))
                                            ) : (
                                                <div className={s.uploadFolderEmpty}>暂无子目录</div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                                <div className={s.uploadHint}>
                                    文件将上传到所选知识空间目录，下一步会进入待入库确认。
                                </div>
                            </div>

                            {uploadFiles.length ? (
                                <div className={s.uploadSelectedFiles}>
                                    <div className={s.uploadLabel}>已选择的文件 ({uploadFiles.length})</div>
                                    {uploadLocalFolderName ? (
                                        <div className={s.uploadFolderNotice}>
                                            <strong>将创建文件夹：{uploadLocalFolderName}</strong>
                                            <span>仅上传所选文件夹根目录下的支持文件，子目录文件不会上传。</span>
                                        </div>
                                    ) : null}
                                    {uploadFiles.map((item) => (
                                        <div key={item.id} className={s.uploadSelectedFile}>
                                            <FileText size={16} />
                                            <div className={s.uploadFileMeta}>
                                                <span>{item.file.name}</span>
                                                <small>{formatFileSize(item.file.size)}</small>
                                            </div>
                                            <button
                                                type="button"
                                                className={s.uploadRemoveButton}
                                                aria-label={`移除${item.file.name}`}
                                                onClick={() => handleRemoveUploadFile(item.id)}
                                            >
                                                <X size={16} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            ) : null}
                            </div>
                            <DialogFooter>
                                <Button variant="outline" className="h-8" onClick={resetUploadDialog}>
                                    取消
                                </Button>
                                <Button className="h-8" disabled={!uploadFiles.length || uploadSubmitting} onClick={() => void handleUploadNext()}>
                                    {uploadSubmitting ? "上传中..." : "下一步"}
                                </Button>
                            </DialogFooter>
                        </div>
                    </DialogContent>
                ) : (
                    <DialogContent className={s.uploadReviewContent} onPointerDownOutside={(event) => event.preventDefault()}>
                        <div data-testid="portal-upload-review-dialog" className={s.uploadReviewInner}>
                            <DialogHeader>
                                <DialogTitle>待入库确认</DialogTitle>
                            </DialogHeader>
                            <div className={s.uploadReviewToolbar}>
                            <input className={s.uploadReviewSearch} placeholder="搜索文档标题..." />
                            <button
                                type="button"
                                className={s.secondaryButton}
                                onClick={() => setUploadReviewRows((prev) => prev.map((row) => ({ ...row, selected: false })))}
                            >
                                取消全选
                            </button>
                            <span>已勾选 {selectedReviewCount} / {uploadReviewRows.length} 个文档</span>
                            </div>
                            <div className={s.uploadReviewTable}>
                            <div className={s.uploadReviewTableHead}>
                                <input
                                    type="checkbox"
                                    aria-label="选择全部待入库文件"
                                    checked={uploadReviewRows.length > 0 && selectedReviewCount === uploadReviewRows.length}
                                    onChange={(event) => {
                                        const checked = event.currentTarget.checked;
                                        setUploadReviewRows((prev) => prev.map((row) => ({ ...row, selected: checked })));
                                    }}
                                />
                                <span>标题</span>
                                <span>推荐存储路径</span>
                                <span>存储路径</span>
                                <span>版本管理</span>
                            </div>
                            {uploadReviewRows.length ? uploadReviewRows.map((row) => (
                                <div key={row.file.id} className={s.uploadReviewRow}>
                                    <input
                                        type="checkbox"
                                        aria-label={`选择${row.file.name}`}
                                        checked={row.selected}
                                        onChange={(event) => {
                                            const checked = event.currentTarget.checked;
                                            setUploadReviewRows((prev) => prev.map((item) => item.file.id === row.file.id ? {
                                                ...item,
                                                selected: checked,
                                            } : item));
                                        }}
                                    />
                                    <div className={s.uploadReviewTitle}>
                                        <small>{row.file.fileEncoding || "-"}</small>
                                        <span>{row.file.name}</span>
                                    </div>
                                    <span className={s.uploadReviewPath}>{row.recommendedFolderName}</span>
                                    <select
                                        className={s.uploadReviewSelect}
                                        aria-label={`${row.file.name}存储路径`}
                                        value={row.storageFolderId ?? ""}
                                        onChange={(event) => {
                                            const selectedValue = event.currentTarget.value;
                                            const nextId = selectedValue || null;
                                            const nextOption = uploadFolderOptions.find((option) => (option.id ?? "") === selectedValue);
                                            setUploadReviewRows((prev) => prev.map((item) => item.file.id === row.file.id ? {
                                                ...item,
                                                storageFolderId: nextId,
                                                storageFolderName: nextOption?.name || "根目录",
                                            } : item));
                                        }}
                                    >
                                        {uploadFolderOptions.map((option) => (
                                            <option key={option.id ?? "root"} value={option.id ?? ""}>
                                                {option.name}
                                            </option>
                                        ))}
                                    </select>
                                    <select
                                        className={s.uploadReviewSelect}
                                        aria-label={`${row.file.name}版本管理`}
                                        value={row.selectedTargetDocumentId ?? ""}
                                        onChange={(event) => {
                                            const selectedValue = event.currentTarget.value;
                                            const value = Number(selectedValue);
                                            setUploadReviewRows((prev) => prev.map((item) => item.file.id === row.file.id ? {
                                                ...item,
                                                selectedTargetDocumentId: Number.isFinite(value) && selectedValue ? value : null,
                                            } : item));
                                        }}
                                    >
                                        <option value="">
                                            {row.candidatesLoading ? "加载中..." : row.candidateError ? "推荐加载失败" : "不关联新版本"}
                                        </option>
                                        {row.candidates.map((candidate) => (
                                            <option key={candidate.target_document_id} value={candidate.target_document_id}>
                                                {candidate.title}
                                            </option>
                                        ))}
                                    </select>
                                </div>
                            )) : (
                                <div className={s.uploadReviewEmpty}>暂无待入库文件</div>
                            )}
                            </div>
                            <DialogFooter>
                                <Button variant="outline" className="h-8" disabled={uploadImporting} onClick={() => setUploadStep("select")}>
                                    返回
                                </Button>
                                <Button className="h-8" disabled={selectedReviewCount === 0 || uploadImporting} onClick={() => void handleStartUploadImport()}>
                                    {uploadImporting ? "导入中..." : `开始导入 (${selectedReviewCount})`}
                                </Button>
                            </DialogFooter>
                        </div>
                    </DialogContent>
                )}
            </Dialog>
        );
    };

    const renderDrawer = () => {
        if (!activePanel) return null;
        const panelTitleMap: Record<PanelKey, string> = {
            properties: "属性",
            time: "时间",
            source: "来源",
            usage: "使用",
            share: "分享",
        };
        const placeholderTextMap: Partial<Record<PanelKey, string>> = {
            time: "文件时间线暂未开放",
            source: "文件来源信息暂未开放",
            usage: "文件使用统计暂未开放",
        };

        return (
            <aside className={s.drawer} data-testid="portal-info-drawer">
                <div className={s.drawerHeader}>
                    <div className={s.drawerTitle}>{panelTitleMap[activePanel]}</div>
                    <button type="button" className={s.toolbarButton} onClick={() => setActivePanel(null)} aria-label="关闭">
                        <X size={14} />
                    </button>
                </div>
                <div className={s.drawerBody}>
                    {activePanel === "properties" ? (
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

                    {activePanel === "time" || activePanel === "source" || activePanel === "usage" ? (
                        <div className={s.detailList}>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>状态</span>
                                <span className={s.detailValue}>暂未开放</span>
                            </div>
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>说明</span>
                                <span className={s.detailValue}>{placeholderTextMap[activePanel]}</span>
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

                </div>
            </aside>
        );
    };

    const renderAiDialog = () => {
        if (!activeSpace || !selectedFile) return null;
        const updatedText = selectedFile.updatedAt ? formatTime(selectedFile.updatedAt) : "";
        const fileSizeText = formatFileSize(selectedFile.size);

        return (
            <Dialog
                open={aiDialogOpen}
                onOpenChange={(open) => {
                    if (!open) setAiDialogOpen(false);
                }}
            >
                <DialogContent
                    close={false}
                    className={s.aiDialogContent}
                    onPointerDownOutside={(event) => event.preventDefault()}
                >
                    <div data-testid="portal-ai-dialog" className={s.aiDialog}>
                        <DialogHeader className={s.aiDialogHeader}>
                            <div className={s.aiFileIcon}>
                                <FileText size={22} />
                            </div>
                            <div className={s.aiFileMeta}>
                                <DialogTitle className={s.aiFileTitle}>{selectedFile.name}</DialogTitle>
                                <div className={s.aiFileFacts}>
                                    <span>{documentPath}</span>
                                    {updatedText ? <span>{updatedText}</span> : null}
                                    {fileSizeText !== "-" ? <span>{fileSizeText}</span> : null}
                                </div>
                            </div>
                            <button
                                type="button"
                                className={s.aiDialogClose}
                                aria-label="关闭AI弹窗"
                                onClick={() => setAiDialogOpen(false)}
                            >
                                <X size={18} />
                            </button>
                        </DialogHeader>
                        <div className={s.aiDialogBody}>
                            <AiAssistantPanel
                                features={{
                                    tools: false,
                                    modelSelect: true,
                                    knowledgeBase: false,
                                    fileUpload: false,
                                }}
                                onClose={() => setAiDialogOpen(false)}
                                noBorder
                                fileChat={{ spaceId: activeSpace.id, fileId: selectedFile.id }}
                            />
                        </div>
                    </div>
                </DialogContent>
            </Dialog>
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
                    <LegacyFileIcon
                        type={getPortalFileIconType(file) as LegacyFileIconType}
                        className={s.treeFileTypeIcon}
                    />
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
        key: PortalToolRailKey;
        title: string;
        icon: typeof PanelRight;
        panelKey?: Extract<PanelKey, "properties" | "time" | "source" | "usage">;
    }> = [
        { key: "toggle", title: "侧边栏展开和关闭", icon: PanelRight },
        { key: "properties", title: "属性", icon: FileText, panelKey: "properties" },
        { key: "time", title: "时间", icon: Clock, panelKey: "time" },
        { key: "source", title: "来源", icon: Link2, panelKey: "source" },
        { key: "usage", title: "使用", icon: BriefcaseBusiness, panelKey: "usage" },
        { key: "permission", title: "权限", icon: LockKeyhole },
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
                    <div className={s.fileActions} data-testid="portal-file-actions">
                        <button
                            type="button"
                            className={s.folderAction}
                            onClick={handleOpenUploadDialog}
                            disabled={!canUploadInPortal}
                            title={canUploadInPortal ? "上传" : "无上传权限"}
                            aria-label="上传"
                        >
                            <Upload size={14} />
                        </button>
                        <button
                            type="button"
                            className={s.folderAction}
                            onClick={showUnavailable}
                            title="网页链接"
                            aria-label="网页链接"
                        >
                            <Globe2 size={14} />
                        </button>
                        <button
                            type="button"
                            className={s.folderAction}
                            onClick={showUnavailable}
                            title="在线创建文档"
                            aria-label="在线创建文档"
                        >
                            <SquarePen size={14} />
                        </button>
                        <button
                            type="button"
                            className={s.folderAction}
                            onClick={() => fileUpload.handleCreateFolder()}
                            disabled={!canCreateFolderInPortal}
                            title={canCreateFolderInPortal ? "新建文件夹" : "无创建权限"}
                            aria-label="新建文件夹"
                        >
                            <FolderPlus size={14} />
                        </button>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <button
                                    type="button"
                                    className={`${s.folderAction} ${statusFilter.length ? s.folderActionActive : ""}`}
                                    title={statusFilter.length ? `筛选：已选择 ${statusFilter.length} 项` : "筛选"}
                                    aria-label="筛选"
                                >
                                    <FunnelIcon size={14} />
                                </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="start" className={s.actionMenu}>
                                <div className={s.actionMenuTitle}>状态</div>
                                {STATUS_FILTER_OPTIONS.map((option) => (
                                    <DropdownMenuCheckboxItem
                                        key={option.status}
                                        checked={statusFilter.includes(option.status)}
                                        onCheckedChange={(checked) => handleToggleStatusFilter(option.status, Boolean(checked))}
                                        onSelect={(event) => event.preventDefault()}
                                    >
                                        {option.label}
                                    </DropdownMenuCheckboxItem>
                                ))}
                            </DropdownMenuContent>
                        </DropdownMenu>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <button
                                    type="button"
                                    className={`${s.folderAction} ${selectedCount > 0 ? s.folderActionActive : ""}`}
                                    disabled={selectedCount === 0}
                                    title={selectedCount > 0 ? `批量操作：已选择 ${selectedCount} 项` : "请先选择文件"}
                                    aria-label="批量操作"
                                >
                                    <ListChecks size={14} />
                                </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="start" className={s.actionMenu}>
                                <DropdownMenuItem onClick={() => void handleBatchDownload()} disabled={!selectedDownloadable}>
                                    <Download size={14} />
                                    <span>批量下载</span>
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => void handleBatchRetry()} disabled={!canBatchRetry}>
                                    <History size={14} />
                                    <span>批量重试</span>
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => void handleBatchDelete()} disabled={!selectedDeletable}>
                                    <X size={14} />
                                    <span>批量删除</span>
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
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
                                <div className={s.docActions} data-testid="portal-document-actions">
                                    <button
                                        type="button"
                                        className={s.iconAction}
                                        title="AI 对话"
                                        aria-label="AI 对话"
                                        onClick={() => {
                                            setActivePanel(null);
                                            setAiDialogOpen(true);
                                        }}
                                    >
                                        <Bot size={16} />
                                    </button>
                                    <button type="button" className={s.iconAction} title="编辑标签" aria-label="编辑标签" onClick={() => setTagModalOpen(true)}>
                                        <SquarePen size={16} />
                                    </button>
                                    <button type="button" className={s.iconAction} title="分享" aria-label="分享" onClick={() => setActivePanel("share")}>
                                        <Share2 size={16} />
                                    </button>
                                    <button type="button" className={s.iconAction} title="下载" aria-label="下载" onClick={() => void handleDownloadSelected()}>
                                        <Download size={16} />
                                    </button>
                                    <button type="button" className={s.iconAction} title="权限管理" aria-label="权限管理" onClick={() => setPermissionOpen(true)}>
                                        <ShieldCheck size={16} />
                                    </button>
                                    <button type="button" className={s.iconAction} title="复制" aria-label="复制" onClick={() => void handleCopyFileEncoding()}>
                                        <Copy size={16} />
                                    </button>
                                </div>
                            </div>
                            <div className={s.divider} />
                            <button
                                type="button"
                                className={s.summaryBar}
                                aria-label="查看文档摘要"
                                aria-expanded={summaryExpanded}
                                aria-controls="portal-summary-detail"
                                onClick={() => {
                                    setActivePanel(null);
                                    setSummaryExpanded((expanded) => !expanded);
                                }}
                            >
                                <div className={s.summaryTitle}>
                                    <FileText size={16} />
                                    文档摘要
                                </div>
                                <div className={s.summaryText}>{selectedFile.summary || "暂无摘要"}</div>
                                <ChevronDown size={14} />
                            </button>
                            {summaryExpanded ? (
                                <div id="portal-summary-detail" data-testid="portal-summary-detail" className={s.summaryDetail}>
                                    {selectedFile.summary || "暂无摘要"}
                                </div>
                            ) : null}
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

                {selectedFile ? renderDrawer() : null}

                {selectedFile ? (
                    <aside className={s.toolRail} data-testid="portal-tool-rail">
                        {toolbarItems.map((item) => {
                            const Icon = item.icon;
                            const active = Boolean(item.panelKey && activePanel === item.panelKey);
                            return (
                                <button
                                    type="button"
                                    key={item.key}
                                    className={`${s.toolbarButton} ${active ? s.toolbarButtonActive : ""}`}
                                    title={item.title}
                                    aria-label={item.title}
                                    aria-pressed={active}
                                    onClick={() => {
                                        if (item.key === "toggle") {
                                            setActivePanel((current) => current ? null : "properties");
                                            return;
                                        }
                                        if (item.key === "permission") {
                                            setActivePanel(null);
                                            setPermissionOpen(true);
                                            return;
                                        }
                                        if (item.panelKey) {
                                            setActivePanel(item.panelKey);
                                        }
                                    }}
                                >
                                    <Icon size={16} />
                                </button>
                            );
                        })}
                    </aside>
                ) : null}
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

            {renderAiDialog()}

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

            {renderUploadDialog()}

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
