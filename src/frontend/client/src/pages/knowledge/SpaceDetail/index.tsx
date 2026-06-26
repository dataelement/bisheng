import { Fragment, useState, useRef, useEffect, useLayoutEffect, useCallback, type MouseEvent } from "react";
import { useRecoilValue } from "recoil";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderPlus } from "lucide-react";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { FileStatus, FileType, KnowledgeFile, KnowledgeSpace, SortDirection, SortType, SpaceRole, VisibilityType, batchDownloadApi, batchRetryApi, getFileDownloadApi } from "~/api/knowledge";
import { Outlined } from "bisheng-icons";
import { NotificationSeverity } from "~/common";
import { buildClientShareUrl } from "~/components/CopyShareLinkButton";
import { useConfirm, useToastContext } from "~/Providers";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { useFileDragDrop } from "../hooks/useFileDragDrop";
import { useKnowledgeMove } from "../hooks/useKnowledgeMove";
import { useKnowledgeMoveDrag } from "../hooks/useKnowledgeMoveDrag";
import { dispatchKnowledgeSpaceFilesRefresh } from "../hooks/useFileManager";
import {
    DEFAULT_MAX_FILE_SIZE_MB,
    getAllowedExtensions,
    getFileInputAccept,
    isKnowledgeItemUploading,
    triggerUrlDownload,
} from "../knowledgeUtils";
import { bishengConfState } from "~/pages/appChat/store/atoms";
import { CompoundSearchInput, SearchParams } from "./CompoundSearchInput";
import { EditTagsModal } from "./EditTagsModal";
import { FileCard } from "./FileCard";
import { FileTable } from "./FileTable";
import { KnowledgeSpaceHeader } from "./KnowledgeSpaceHeader";
import { KnowledgeSpaceShareDialog } from "./KnowledgeSpaceShareDialog";
import { MoveToDialog } from "./MoveToDialog";
import { VersionManagementDialog } from "./VersionManagementDialog";
import { VersionHistorySheet } from "./VersionHistorySheet";
import { SimilarDocumentDialog } from "./SimilarDocumentDialog";
import { SelectionPathBreadcrumb } from "./SelectionPathBreadcrumb";
import { canOpenPermissionDialog, checkPermission } from "~/api/permission";
import {
    hasKnowledgeSpacePermission,
    useKnowledgeSpaceActionPermissions,
} from "../hooks/useKnowledgeSpacePermissions";
import { useLocalize, usePrefersMobileLayout, useScrollRevealRef, useVersionManagementEnabled } from "~/hooks";
import {
    knowledgeSpaceDropdownSurfaceClassName,
    SidebarListMoreMenuContent,
    sidebarListMoreMenuItemClassName,
    sidebarListMoreMenuIconClassName,
    sidebarListMoreMenuLabelClassName,
    sidebarListMoreMenuDangerItemClassName,
    sidebarListMoreMenuDangerIconClassName,
    sidebarListMoreMenuDangerLabelClassName,
} from "~/components/SidebarListMoreMenu";
import { cn, getFullWidthLength } from "~/utils";

interface KnowledgeSpaceContentProps {
    space: KnowledgeSpace;
    files: KnowledgeFile[];
    total: number;
    /** Infinite scroll: load the next page (appends). */
    onLoadMore: () => void;
    /** Whether more pages remain to load. */
    hasMore: boolean;
    loading: boolean;
    onSearch: (params: SearchParams) => void;
    onFilterStatus: (status: FileStatus[]) => void;
    onSort: (sortBy: SortType | undefined, direction: SortDirection | undefined) => void;
    onNavigateFolder: (folderId?: string) => void;
    onUploadFile: (files?: FileList | File[]) => void;
    onUploadFolder: (
        fileList: FileList | File[],
        options: { allowedExtensions: readonly string[]; maxSizeMB: number },
    ) => void;
    onCreateFolder: () => void;
    onDownloadFile: (fileId: string) => void;
    onRenameFile: (fileId: string, newName: string) => void;
    onDeleteFile: (fileId: string) => void;
    /** Optimistic batch delete: removes the given ids in place. Resolves true on success. */
    onBatchDeleteFiles: (ids: Array<string | number>) => Promise<boolean>;
    onEditTags: (fileId: string) => void;
    onRetryFile: (fileId: string) => void;
    currentPath: Array<{ id?: string; name: string }>;
    currentFolderId?: string;
    onDragStateChange?: (isDragging: boolean, error?: string | null) => void;
    uploadingFiles?: KnowledgeFile[];
    creatingFolder?: KnowledgeFile | null;
    /** Placeholder folder card shown while a dragged/picked folder batch uploads. */
    uploadingFolder?: KnowledgeFile | null;
    onCancelCreateFolder?: () => void;
    onCreateSpace?: () => void;
    onGoKnowledgeSquare?: () => void;
    /** Mobile top bar — provided by the Knowledge page (index.tsx). */
    onOpenSystemMenu?: () => void;
    onToggleSpaceList?: () => void;
    spaceListOpen?: boolean;
    /** Delete current space (navigates back to the list); permission-gated by the menu. */
    onDeleteSpace?: () => void;
    /** Open the search page from the top-bar search icon. */
    onOpenSearch?: () => void;
    /** Mobile full-page search mode: replaces the top bar with an inline search header. */
    searchMode?: boolean;
    onCloseSearch?: () => void;
    /** Notify the page when a mobile batch selection is active, so it can hide the AI dock. */
    onSelectionActiveChange?: (active: boolean) => void;
}

export function KnowledgeSpaceContent({
    space,
    files,
    total,
    onLoadMore,
    hasMore,
    loading,
    onSearch,
    onFilterStatus,
    onSort,
    onNavigateFolder,
    onUploadFile,
    onUploadFolder,
    onCreateFolder,
    onDownloadFile,
    onRenameFile,
    onDeleteFile,
    onBatchDeleteFiles,
    onEditTags,
    onRetryFile,
    currentPath,
    currentFolderId,
    onDragStateChange,
    uploadingFiles = [],
    creatingFolder,
    uploadingFolder = null,
    onCancelCreateFolder,
    onCreateSpace,
    onGoKnowledgeSquare,
    onOpenSystemMenu,
    onToggleSpaceList,
    spaceListOpen = false,
    onDeleteSpace,
    onOpenSearch,
    searchMode = false,
    onCloseSearch,
    onSelectionActiveChange,
}: KnowledgeSpaceContentProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const fileListScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
    const tableScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
    const displayFiles = [
        ...(creatingFolder ? [creatingFolder] : []),
        // In-progress folder upload: show its placeholder card (keyed to the space +
        // folder it was started in, like the file placeholders below) so it stays put
        // when the user navigates elsewhere mid-upload.
        ...(uploadingFolder &&
            String(uploadingFolder.spaceId) === String(space.id) &&
            String(uploadingFolder.parentId ?? "") === String(currentFolderId ?? "")
            ? [uploadingFolder]
            : []),
        // Uploading placeholders are keyed to the space AND folder they were
        // started in (placeholder.parentId = the folder at upload time). Filter to
        // the active space + current folder so an in-progress root upload does not
        // leak into a subfolder's list (and vice versa), and uploads in space A
        // don't show in space B after switching.
        ...uploadingFiles.filter(
            (f) =>
                String(f.spaceId) === String(space.id) &&
                String(f.parentId ?? "") === String(currentFolderId ?? ""),
        ),
        ...files
    ];

    // Infinite scroll: trigger the next page when the scroll container nears its bottom.
    const handleListScroll = (e: React.UIEvent<HTMLDivElement>) => {
        if (!hasMore || loading) return;
        const el = e.currentTarget;
        if (el.scrollHeight - el.scrollTop - el.clientHeight <= 240) {
            onLoadMore();
        }
    };

    const [searchQuery, setSearchQuery] = useState("");
    const [searchTagIds, setSearchTagIds] = useState<number[]>([]);
    const [viewMode, setViewModeState] = useState<"card" | "list">(() => {
        if (typeof window === "undefined") return "list";
        return localStorage.getItem("knowledge-view-mode") === "card" ? "card" : "list";
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
    const [contextMenuOpen, setContextMenuOpen] = useState(false);
    const [contextMenuPosition, setContextMenuPosition] = useState({ x: 0, y: 0 });

    // Card view: compute columns by *container width* (not viewport width).
    // Thresholds (container width):
    // >=1296: 7, 1024-1295: 6, 768-1023: 5, 600-767: 4, 480-599: 3, 320-479: 2, <320: 1
    const cardGridRef = useRef<HTMLDivElement | null>(null);
    const calcCols = (w: number) => {
        if (w >= 1296) return 7;
        if (w >= 1024) return 6;
        if (w >= 768) return 5;
        if (w >= 600) return 4;
        if (w >= 480) return 3;
        if (w >= 320) return 2;
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
        // 无文件时 grid 未挂载，等 displayFiles 变化后 effect 会再跑
        if (!el) return;

        // Prefer滚动容器宽度；再观察上一层 flex 容器，避免分栏/侧栏变化时仅子节点未触发 RO 的边缘情况
        const scrollParent = el.parentElement as HTMLElement | null;
        const flexAncestor = scrollParent?.parentElement as HTMLElement | null;
        const getWidth = () =>
            scrollParent?.clientWidth || el.clientWidth || flexAncestor?.clientWidth || 0;

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
        if (scrollParent) ro.observe(scrollParent);
        if (flexAncestor) ro.observe(flexAncestor);

        // 窗口缩放、部分环境下 RO 漏触发时的兜底
        window.addEventListener("resize", apply);

        return () => {
            if (rafId) window.cancelAnimationFrame(rafId);
            window.removeEventListener("resize", apply);
            ro.disconnect();
        };
    }, [viewMode, displayFiles.length]);

    useEffect(() => {
        setSelectedFiles(new Set());
        setSearchQuery("");
        setSearchTagIds([]); // 切换空间时清空搜索条件
    }, [space.id]);

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    // Delete is owner-only in the backend ReBAC model (can_delete maps to `owner`);
    // a space manager (ADMIN) does NOT inherit it. Unlike read/edit/manage tiers,
    // the delete probe must not short-circuit on the manager role — only the space
    // creator is the implicit owner of every entry. Everyone else (managers, and
    // platform super-admins for spaces they didn't create) falls through to the
    // per-resource backend probe, which is the source of truth: it still grants
    // delete on files the user owns, and on every file for a platform super-admin.
    const isOwner = space.role === SpaceRole.CREATOR;
    const { permissions: spaceActionPermissions, ensureSpacePermissions } = useKnowledgeSpaceActionPermissions([space.id]);
    const canShareSpace = isAdmin || hasKnowledgeSpacePermission(
        spaceActionPermissions,
        space.id,
        "share_space",
    );
    const canDeleteSpace = isAdmin || hasKnowledgeSpacePermission(
        spaceActionPermissions,
        space.id,
        "delete_space",
    );
    // Permission management — mirrors the desktop sidebar (KnowledgeSpaceItem) gating.
    const canManageMembers = isAdmin || hasKnowledgeSpacePermission(
        spaceActionPermissions,
        space.id,
        "manage_space_relation",
    );
    // ─── Version Management ──────────────────────────────────────────────
    const versionManagementEnabled = useVersionManagementEnabled();
    const queryClient = useQueryClient();
    const spaceIdNum = Number(space.id);

    const [versionMgmtFile, setVersionMgmtFile] = useState<KnowledgeFile | null>(null);
    const [versionHistoryFile, setVersionHistoryFile] = useState<KnowledgeFile | null>(null);
    const [similarDialogOpen, setSimilarDialogOpen] = useState(false);
    // File ids (KnowledgeFile.id) the similar-document dialog is scoped to — snapshotted
    // from the current selection when the batch "处理相似文档" entry is triggered.
    const [similarRestrictIds, setSimilarRestrictIds] = useState<string[]>([]);

    // Open the similar-document dialog scoped to the currently selected files.
    const handleProcessSimilar = () => {
        setSimilarRestrictIds(Array.from(selectedFiles));
        setSimilarDialogOpen(true);
    };

    // Invalidate pending-similar and trigger file list refresh after any version action.
    const handleVersionAction = () => {
        queryClient.invalidateQueries({ queryKey: ["pending-similar", spaceIdNum] });
        queryClient.invalidateQueries({ queryKey: ["file-versions"] });
        // Signal parent to reload file list (same pattern used by batch delete/retry).
        onDeleteFile("");
    };

    // Share = copy the space share link (mirrors the desktop CopyShareLinkButton);
    // only when the space is shareable and not private.
    const showShareInMenu = canShareSpace && space.visibility !== VisibilityType.PRIVATE;
    const handleCopyShareLink = async () => {
        try {
            await navigator.clipboard.writeText(buildClientShareUrl(`/knowledge/share/${space.id}`));
            showToast({ message: localize("com_knowledge.share_link_copied"), severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: localize("com_knowledge.share_link_copy_failed"), severity: NotificationSeverity.ERROR });
        }
    };
    const [canCreateFolder, setCanCreateFolder] = useState(false);
    const [canUploadFile, setCanUploadFile] = useState(false);
    // Move permission is separate from upload (both can_edit tier, but a role may
    // grant one without the other). Files and folders have independent move
    // permissions (move_file / move_folder) — probe both so a user with only
    // one of them isn't blocked on the other. Drives the move menu greyed state.
    const [canMoveFile, setCanMoveFile] = useState(false);
    const [canMoveFolder, setCanMoveFolder] = useState(false);
    const isSearching = searchQuery.trim().length > 0 || searchTagIds.length > 0;
    const [permTarget, setPermTarget] = useState<{
        id: string;
        name: string;
        type: "folder" | "knowledge_file" | "knowledge_space";
    } | null>(null);
    const [permissionEntryIds, setPermissionEntryIds] = useState<Set<string>>(new Set());
    const [renameEntryIds, setRenameEntryIds] = useState<Set<string>>(new Set());
    const [deleteEntryIds, setDeleteEntryIds] = useState<Set<string>>(new Set());
    const [downloadEntryIds, setDownloadEntryIds] = useState<Set<string>>(new Set());
    const permissionEntryProbeKey = displayFiles
        .filter((file) => !file.isCreating && /^\d+$/.test(String(file.id)))
        .map((file) => `${file.id}:${file.type}`)
        .join("|");
    const canUseAddActions = canCreateFolder && !isSearching;

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
            checkPermission(
                objectType,
                objectId,
                "can_edit",
                "move_file",
                { signal: controller.signal },
            ),
            checkPermission(
                objectType,
                objectId,
                "can_edit",
                "move_folder",
                { signal: controller.signal },
            ),
        ]).then(([createFolderResult, uploadFileResult, moveFileResult, moveFolderResult]) => {
            if (cancelled) return;
            setCanCreateFolder(
                createFolderResult.status === "fulfilled" && Boolean(createFolderResult.value?.allowed)
            );
            setCanUploadFile(
                uploadFileResult.status === "fulfilled" && Boolean(uploadFileResult.value?.allowed)
            );
            setCanMoveFile(
                moveFileResult.status === "fulfilled" && Boolean(moveFileResult.value?.allowed)
            );
            setCanMoveFolder(
                moveFolderResult.status === "fulfilled" && Boolean(moveFolderResult.value?.allowed)
            );
        }).catch(() => {
            if (!cancelled) {
                setCanCreateFolder(false);
                setCanUploadFile(false);
                setCanMoveFile(false);
                setCanMoveFolder(false);
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [currentFolderId, space.id]);

    // F040: per-file action permissions (rename / download / delete / manage) are NO
    // LONGER probed eagerly for every file on list load (that fired ~4 checkPermission
    // per file → hundreds of requests). They are resolved lazily when the user opens a
    // file's "⋯" action menu, via `ensureFilePermissions` below. `permissionEntryIds`
    // etc. start empty and get populated on demand; menu items gate on them (fail-closed
    // until the check resolves). Admin (rename/download/manage) and space-owner (delete)
    // short-circuit without a request, matching the previous behavior.
    const checkedFileIdsRef = useRef<Set<string>>(new Set());

    // Drop lazily-cached grants when the listed files / folder change, so a re-opened
    // menu re-checks against the new context (mirrors the old probe-key re-fetch).
    useEffect(() => {
        checkedFileIdsRef.current = new Set();
        setPermissionEntryIds(new Set());
        setRenameEntryIds(new Set());
        setDownloadEntryIds(new Set());
        setDeleteEntryIds(new Set());
    }, [permissionEntryProbeKey]);

    const ensureFilePermissions = useCallback(
        async (file: KnowledgeFile) => {
            const id = String(file.id);
            if (file.isCreating || !/^\d+$/.test(id)) return;
            if (checkedFileIdsRef.current.has(id)) return; // already resolved for this file
            checkedFileIdsRef.current.add(id);

            const resourceType = file.type === FileType.FOLDER ? "folder" : "knowledge_file";
            const grant = (setter: (updater: (prev: Set<string>) => Set<string>) => void) =>
                setter((prev) => new Set(prev).add(id));

            // Admin holds rename/download/manage; space owner holds delete — no request.
            if (isAdmin) {
                grant(setPermissionEntryIds);
                grant(setRenameEntryIds);
                grant(setDownloadEntryIds);
            }
            if (isOwner) {
                grant(setDeleteEntryIds);
            }

            const tasks: Promise<unknown>[] = [];
            if (!isAdmin) {
                tasks.push(
                    canOpenPermissionDialog(resourceType, file.id)
                        .then((ok) => { if (ok) grant(setPermissionEntryIds); })
                        .catch(() => { }),
                    checkPermission(resourceType, file.id, "can_edit", file.type === FileType.FOLDER ? "rename_folder" : "rename_file")
                        .then((r) => { if (r.allowed) grant(setRenameEntryIds); })
                        .catch(() => { }),
                    checkPermission(resourceType, file.id, "can_read", file.type === FileType.FOLDER ? "download_folder" : "download_file")
                        .then((r) => { if (r.allowed) grant(setDownloadEntryIds); })
                        .catch(() => { }),
                );
            }
            if (!isOwner) {
                tasks.push(
                    checkPermission(resourceType, file.id, "can_delete", file.type === FileType.FOLDER ? "delete_folder" : "delete_file")
                        .then((r) => { if (r.allowed) grant(setDeleteEntryIds); })
                        .catch(() => { }),
                );
            }
            await Promise.all(tasks);
        },
        [isAdmin, isOwner],
    );

    // Read max file size from env config (MB), fallback to default 200MB
    const bishengConfig = useRecoilValue(bishengConfState);
    const maxFileSizeMB = bishengConfig?.uploaded_files_maximum_size ?? DEFAULT_MAX_FILE_SIZE_MB;
    const maxFileSizeBytes = maxFileSizeMB * 1024 * 1024;
    const enableEtl4lm = bishengConfig?.enable_etl4lm ?? false;
    const allowedExtensions = getAllowedExtensions(enableEtl4lm);
    const fileInputAccept = getFileInputAccept(enableEtl4lm);

    // ─── File Upload Trigger ─────────────────────────────────────────────
    const fileInputRef = useRef<HTMLInputElement>(null);
    const folderInputRef = useRef<HTMLInputElement>(null);

    const triggerUpload = () => {
        if (!canUploadFile) return;
        fileInputRef.current?.click();
    };

    const triggerUploadFolder = () => {
        if (!canUploadFile) return;
        folderInputRef.current?.click();
    };

    useEffect(() => {
        if (!canUseAddActions) {
            setContextMenuOpen(false);
        }
    }, [canUseAddActions]);

    const handleContentContextMenu = (e: MouseEvent<HTMLDivElement>) => {
        if (!canUseAddActions) return;
        const target = e.target;
        if (target instanceof Element && target.closest("[data-knowledge-file-item]")) return;

        e.preventDefault();
        setContextMenuPosition({ x: e.clientX, y: e.clientY });
        setContextMenuOpen(true);
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
                if (!ext || !allowedExtensions.includes(ext)) {
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

    // Folder upload: hand the full FileList to the hook, which handles
    // hidden-folder rejection, dup-name check, count cap, and silent filtering
    // (oversize / unsupported / hidden) — see useFileUpload.handleUploadFolder.
    const handleFolderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const filesList = e.target.files;
        if (filesList && filesList.length > 0 && canUploadFile) {
            onUploadFolder(filesList, { allowedExtensions, maxSizeMB: maxFileSizeMB });
        }
        if (folderInputRef.current) folderInputRef.current.value = "";
    };

    // ─── Drag and drop ──────────────────────────────────────────────────
    const { handleDragEnter, handleDragLeave, handleDragOver, handleDrop } = useFileDragDrop({
        onDragStateChange,
        onUploadFile: canUploadFile ? onUploadFile : () => undefined,
        // Without this the folder-drop branch in handleDrop is skipped (it
        // guards on `onUploadFolder` being defined), so dropping a folder did
        // nothing. Gate on canUploadFile like onUploadFile.
        onUploadFolder: canUploadFile ? onUploadFolder : undefined,
        maxFileSizeMB,
        enableEtl4lm,
    });

    const handleSearch = (params: SearchParams) => {
        setSearchQuery(params.keyword);
        setSearchTagIds(params.tagIds);
        setSelectedFiles(new Set());
        onSearch(params);
    };

    const handleStatusFilter = (status: FileStatus, checked: boolean) => {
        const coupled = [status];
        const newFilter = checked
            ? [...statusFilter, ...coupled.filter(s => !statusFilter.includes(s))]
            : statusFilter.filter(s => !coupled.includes(s));
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

    // An uploading folder placeholder has only a temp id and no backend identity —
    // it must not be selectable (neither individually nor via select-all).
    const isFolderUploadPlaceholder = (f: KnowledgeFile) =>
        f.type === FileType.FOLDER && isKnowledgeItemUploading(f);

    const handleSelectFile = (fileId: string, selected: boolean) => {
        const target = displayFiles.find((f) => f.id === fileId);
        if (target && isFolderUploadPlaceholder(target)) return;
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
        // Skip uploading folder placeholders so select-all never picks them up.
        const selectable = displayFiles.filter((f) => !isFolderUploadPlaceholder(f));
        if (isAllSelectedOnPage) {
            selectable.forEach(f => newSelected.delete(f.id));
        } else {
            selectable.forEach(f => newSelected.add(f.id));
        }
        setSelectedFiles(newSelected);
    };

    const handleBatchDownload = async () => {
        const selectedList = displayFiles.filter(f => selectedFiles.has(f.id));
        const canDownloadSelected = selectedList.length > 0 && selectedList.every((file) =>
            downloadEntryIds.has(file.id)
        );
        if (!canDownloadSelected) {
            showToast({ message: localize("com_knowledge.download_failed"), status: "error" });
            return;
        }
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

    // F034: move selected files/folders (same-space or cross-space) via MoveToDialog,
    // plus drag-to-folder move (dropMoveToFolder wired into the table/card drag sources).
    const { moveDialogOpen, setMoveDialogOpen, openMove, requestBatchMove, handleMoveConfirm, dropMoveToFolder } = useKnowledgeMove({
        spaceId: space.id,
        onMoved: () => {
            setSelectedFiles(new Set());
            queryClient.invalidateQueries({ queryKey: ["file-versions"] });
            onDeleteFile(""); // generic "file list changed, reload" signal (same as batch delete).
            // Refresh the left sidebar folder tree(s). No spaceId → global refresh,
            // so a cross-space move updates both the source and target trees.
            dispatchKnowledgeSpaceFilesRefresh();
        },
    });
    const handleBatchMove = () => {
        const selected = displayFiles.filter((f) => selectedFiles.has(f.id));
        // Uploading placeholders have no backend id yet → can't be moved. Surface
        // them in the partial-move dialog so the user can still move the rest.
        const uploading = selected.filter((f) => isKnowledgeItemUploading(f));
        const movable = selected.filter((f) => !isKnowledgeItemUploading(f));
        if (!movable.length && !uploading.length) return;
        // Frontend pre-flight (space-level move permission, simple block): if the user
        // can't move in this space, every movable item is denied → block dialog before
        // the picker. The backend re-validates per item on the move.
        const permitted = canMoveFile ? movable : [];
        const denied = canMoveFile ? [] : movable;
        requestBatchMove(permitted, denied, uploading);
    };

    const handleSingleDownload = async (fileId: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        const isFolder = file?.type === FileType.FOLDER;
        if (!downloadEntryIds.has(fileId)) {
            showToast({ message: localize("com_knowledge.download_failed"), status: "error" });
            return;
        }
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
                const downloadData = await getFileDownloadApi(String(space.id), fileId);
                const downloadUrl = file?.fileSource === 'channel'
                    ? downloadData.preview_url || downloadData.original_url
                    : downloadData.original_url;
                if (!downloadUrl) { showToast({ message: localize("com_knowledge.get_download_link_failed"), status: "error" }); return; }
                triggerUrlDownload(downloadUrl, file?.name);
            }
        } catch {
            showToast({ message: localize("com_knowledge.download_failed"), status: "error" });
        }
    };

    const handlePreviewFile = (fileId: string, explicitFileName?: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        // Version files aren't in displayFiles, so accept an explicit name for them.
        const fileName = explicitFileName || file?.name || localize("com_knowledge.unknown_file");
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
            description: `${localize("com_knowledge.confirm_delete_files_count", { 0: selectedFiles.size })}${localize("com_knowledge.delete_irreversible_warning")}`,
            variant: "destructive",
        });

        if (!confirmed) return;

        if (!canBatchDelete) {
            showToast({ message: localize("com_knowledge.batch_delete_failed"), status: "error" });
            return;
        }

        // Optimistic batch delete (handled by the parent): rows are dropped from
        // the list in place — keeps the scroll position and works regardless of
        // which page they were loaded from. The parent rolls back on API failure.
        const ids = selectedList.map(f => f.id);
        setSelectedFiles(new Set());
        const ok = await onBatchDeleteFiles(ids);
        if (ok) {
            showToast({ message: localize("com_knowledge.batch_delete_success"), status: "success" });
        } else {
            showToast({ message: localize("com_knowledge.batch_delete_failed"), status: "error" });
        }
    };

    const handleDelete = async (fileId: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        if (!file) return;

        const isFolder = file.type === FileType.FOLDER;
        if (!deleteEntryIds.has(fileId)) {
            showToast({ message: localize("com_knowledge.delete_failed"), status: "error" });
            return;
        }

        const confirmed = await confirm({
            description: isFolder
                ? `${localize("com_knowledge.confirm_delete_folder_name", { 0: file.name })}${localize("com_knowledge.delete_folder_permanent_warning")}`
                : `${localize("com_knowledge.confirm_delete_file")}${localize("com_knowledge.delete_irreversible_warning")}`,
            variant: "destructive",
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
                f.status === FileStatus.VIOLATION ||
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
            f.status === FileStatus.VIOLATION ||
            (f.type === FileType.FOLDER && f.successFileNum! < f.fileNum!)
        )
    );
    const hasFoldersSelected = displayFiles.some(f => selectedFiles.has(f.id) && f.type === FileType.FOLDER);
    const selectedList = displayFiles.filter(f => selectedFiles.has(f.id));
    const selectionHasFile = selectedList.some((f) => f.type !== FileType.FOLDER);
    // Batch move requires the matching move permission for every kind in the
    // selection: folders need move_folder, files need move_file (a role may
    // grant only one). Uploading placeholders no longer block the entry — the
    // move flow warns about them and lets the user move the rest (handleBatchMove).
    const canBatchMove =
        selectedList.length > 0 &&
        (!hasFoldersSelected || canMoveFolder) &&
        (!selectionHasFile || canMoveFile);
    const canBatchDelete = selectedList.length > 0 && selectedList.every((file) =>
        deleteEntryIds.has(file.id)
    );
    const canBatchDownload = selectedList.length > 0 && selectedList.every((file) =>
        downloadEntryIds.has(file.id)
    );
    // "处理相似文档" uses union semantics (like batch retry's hasFailedFiles): the entry
    // appears whenever ANY selected file is a pending similar document. The dialog is then
    // scoped to exactly the selected files (see handleProcessSimilar).
    const hasSimilarSelected = selectedList.some((f) => f.has_similar && !f.is_multi_version && f.status === FileStatus.SUCCESS);

    // Mobile only ever shows the list form — never the multi-column card grid.
    const effectiveViewMode: "card" | "list" = isH5 ? "list" : viewMode;
    // Search page starts empty: show results only once a keyword/tag search is active.
    const suppressList = searchMode && !isSearching;

    // ─── Mobile batch action bar ────────────────────────────────────────
    // Shown at the bottom (replacing the AI dock) once any file is selected. Which
    // actions appear mirrors the desktop toolbar exactly (same permission/status gates).
    const selectionActive = isH5 && selectedFiles.size > 0;
    useEffect(() => {
        onSelectionActiveChange?.(selectionActive);
    }, [selectionActive, onSelectionActiveChange]);

    // Permission management is a single-target action: only with exactly one selected item,
    // and only when the user is allowed to manage its permission (permissionEntryIds is the
    // permission-probed set, so this respects the user's permission).
    const singleSelectedId = selectedFiles.size === 1 ? Array.from(selectedFiles)[0] : undefined;
    const canManageSinglePermission = !!singleSelectedId && permissionEntryIds.has(singleSelectedId);

    type BatchAction = { key: string; label: string; Icon: React.ComponentType<{ className?: string }>; onClick: () => void; danger?: boolean };
    const batchActions: BatchAction[] = [
        canBatchDownload && {
            key: "download",
            label: localize("com_knowledge.download"),
            Icon: Outlined.Download,
            // A single selected file uses the single-file download (no zip); multiple → batch zip.
            onClick: () => (selectedFiles.size === 1 ? handleSingleDownload(Array.from(selectedFiles)[0]) : handleBatchDownload()),
        },
        (isAdmin && !hasFoldersSelected) && { key: "tag", label: localize("com_knowledge.batch_add_tags"), Icon: Outlined.Tag, onClick: handleBatchTag },
        (isAdmin && hasFailedFiles) && { key: "retry", label: localize("com_knowledge.retry"), Icon: Outlined.Refresh, onClick: handleBatchRetry },
        (versionManagementEnabled && canManageMembers && hasSimilarSelected) && { key: "similar", label: localize("com_knowledge.version.header_process_similar_label"), Icon: Outlined.FileSearch, onClick: handleProcessSimilar },
        canBatchMove && { key: "move", label: localize("com_knowledge.move"), Icon: Outlined.MoveToFolder, onClick: handleBatchMove },
        canManageSinglePermission && { key: "permission", label: localize("com_permission.manage_permission"), Icon: Outlined.PeopleSafe, onClick: () => handleManagePermission(singleSelectedId!) },
        canBatchDelete && { key: "delete", label: localize("com_knowledge.delete"), Icon: Outlined.Delete, onClick: handleBatchDelete, danger: true },
    ].filter(Boolean) as BatchAction[];
    // Up to 3 slots inline; if more actions exist, the last slot becomes a "更多" dropdown.
    const MAX_INLINE = 3;
    const hasOverflow = batchActions.length > MAX_INLINE;
    const inlineActions = hasOverflow ? batchActions.slice(0, MAX_INLINE - 1) : batchActions;
    const overflowActions = hasOverflow ? batchActions.slice(MAX_INLINE - 1) : [];

    // F034: drag-move wiring for the card grid (table view wires its own internally).
    const cardDrag = useKnowledgeMoveDrag({
        files: displayFiles,
        selectedFiles,
        onMoveToFolder: canUploadFile ? (folderId, items, folderName) => dropMoveToFolder(items, folderId, folderName) : undefined,
    });

    return (
        <div
            className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-hidden rounded-lg px-4 max-[767px]:overflow-hidden max-[767px]:px-0"
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
                accept={fileInputAccept}
            />
            {/* Hidden Folder Input — `webkitdirectory` makes the picker select a
                directory; each File carries its `webkitRelativePath`. No `accept`:
                extension filtering is done silently in the hook per spec. */}
            <input
                type="file"
                multiple
                className="hidden"
                ref={folderInputRef}
                onChange={handleFolderChange}
                // `webkitdirectory`/`directory` are non-standard but accepted by
                // every browser we ship to; React typings don't list them.
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                {...({ webkitdirectory: "", directory: "" } as any)}
            />
            {/* Mobile full-page search header: inline search box (scope + keyword + tags) + 取消.
                Per design (Figma 11495:16476): the search-box+cancel row is 64px tall, no top padding;
                tags flow immediately below. The 64px row is owned by CompoundSearchInput pageMode. */}
            {isH5 && searchMode && (
                <div className="shrink-0 rounded-t-xl bg-white px-4">
                    <CompoundSearchInput
                        pageMode
                        spaceId={space.id}
                        isRoot={currentPath.length === 0}
                        onSearch={handleSearch}
                        trailing={
                            <button
                                type="button"
                                onClick={() => {
                                    handleSearch({ scope: currentPath.length === 0 ? "all" : "current", tagIds: [], keyword: "" });
                                    onCloseSearch?.();
                                }}
                                className="shrink-0 text-sm text-[#999]"
                            >
                                {localize("com_knowledge.cancel")}
                            </button>
                        }
                    />
                </div>
            )}

            {/* Mobile top bar: system menu + space-name dropdown + search/sort/more.
                Search/sort/more are greyed + disabled while the space-list dropdown is open. */}
            {isH5 && !searchMode && (
                /* Root has no padding on mobile; the inner row's px-4 gives the 16px gutter. */
                <div className="shrink-0 rounded-t-xl bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
                    <div className="flex h-11 w-full min-w-0 items-center gap-3 px-4">
                        {/* Left group — fixed width that mirrors the right group, so the
                            center title stays screen-centered even when truncated.
                            84px = search(20) + gap(12) + sort(20) + gap(12) + more(20). */}
                        <div className="flex min-w-[84px] shrink-0 items-center justify-start">
                            <button
                                type="button"
                                aria-label={localize("com_nav_open_sidebar")}
                                onClick={() => onOpenSystemMenu?.()}
                                disabled={spaceListOpen}
                                className={cn("inline-flex size-5 shrink-0 items-center justify-center text-[#212121]", spaceListOpen && "pointer-events-none text-[#C9CDD4]")}
                            >
                                <Outlined.SidebarMenu className="size-5" />
                            </button>
                        </div>
                        {/* Center group — title grows then truncates while staying centered */}
                        <button
                            type="button"
                            onClick={() => onToggleSpaceList?.()}
                            aria-expanded={spaceListOpen}
                            className="flex min-w-0 flex-1 items-center justify-center gap-1 outline-none"
                        >
                            <span className="truncate text-[16px] font-medium leading-6 text-[#212121]">
                                {currentPath.length > 0 ? currentPath[currentPath.length - 1].name : space.name}
                            </span>
                            <Outlined.Down className={cn("size-5 shrink-0 text-[#86909C] transition-transform", spaceListOpen && "rotate-180")} />
                        </button>
                        {/* Right group — same fixed width as the left group */}
                        <div className="flex min-w-[84px] shrink-0 items-center justify-end gap-3">
                            <button
                                type="button"
                                aria-label={localize("com_knowledge.search")}
                                onClick={() => onOpenSearch?.()}
                                className={cn("inline-flex size-5 shrink-0 items-center justify-center text-[#212121]", spaceListOpen && "pointer-events-none text-[#C9CDD4]")}
                            >
                                <Outlined.Search className="size-5" />
                            </button>
                            <DropdownMenu onOpenChange={(open) => { if (open) ensureSpacePermissions(space.id); }}>
                                <DropdownMenuTrigger asChild disabled={spaceListOpen}>
                                    <button
                                        type="button"
                                        aria-label={localize("com_knowledge.sort_field")}
                                        className={cn("inline-flex size-5 shrink-0 items-center justify-center text-[#212121] outline-none", spaceListOpen && "pointer-events-none text-[#C9CDD4]")}
                                    >
                                        <Outlined.Sort className="size-5" />
                                    </button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end" className={knowledgeSpaceDropdownSurfaceClassName}>
                                    <div className="px-2 py-1.5 text-xs font-medium text-[#86909c]">{localize("com_knowledge.sort_field")}</div>
                                    {[
                                        { value: SortType.NAME, label: localize("com_knowledge.sort_by_name_label") },
                                        { value: SortType.TYPE, label: localize("com_knowledge.sort_by_type_label") },
                                        { value: SortType.UPDATE_TIME, label: localize("com_knowledge.sort_by_update_time_label") },
                                    ].map((opt) => (
                                        <DropdownMenuItem
                                            key={opt.value}
                                            onClick={() => handleSort(opt.value)}
                                            className="flex items-center justify-between gap-6"
                                        >
                                            <span>{opt.label}</span>
                                            {sortBy === opt.value && (
                                                <span className="shrink-0 text-xs text-[#86909c]">
                                                    {sortDirection === SortDirection.ASC ? "↑" : "↓"}
                                                </span>
                                            )}
                                        </DropdownMenuItem>
                                    ))}
                                </DropdownMenuContent>
                            </DropdownMenu>
                            <DropdownMenu onOpenChange={(open) => { if (open) ensureSpacePermissions(space.id); }}>
                                <DropdownMenuTrigger asChild disabled={spaceListOpen}>
                                    <button
                                        type="button"
                                        aria-label={localize("com_knowledge.more")}
                                        className={cn("inline-flex size-5 shrink-0 items-center justify-center text-[#212121] outline-none", spaceListOpen && "pointer-events-none text-[#C9CDD4]")}
                                    >
                                        <Outlined.MoreCircle className="size-5" />
                                    </button>
                                </DropdownMenuTrigger>
                                <SidebarListMoreMenuContent>
                                    {canUploadFile && (
                                        <DropdownMenuItem className={sidebarListMoreMenuItemClassName} onClick={triggerUpload}>
                                            <Outlined.Upload className={sidebarListMoreMenuIconClassName} />
                                            <span className={sidebarListMoreMenuLabelClassName}>{localize("com_knowledge.upload_file")}</span>
                                        </DropdownMenuItem>
                                    )}
                                    {canCreateFolder && (
                                        <DropdownMenuItem className={sidebarListMoreMenuItemClassName} onClick={() => onCreateFolder()}>
                                            <FolderPlus className={sidebarListMoreMenuIconClassName} />
                                            <span className={sidebarListMoreMenuLabelClassName}>{localize("com_knowledge.new_folder")}</span>
                                        </DropdownMenuItem>
                                    )}
                                    {showShareInMenu && (
                                        <DropdownMenuItem className={sidebarListMoreMenuItemClassName} onClick={handleCopyShareLink}>
                                            <Outlined.Share className={sidebarListMoreMenuIconClassName} />
                                            <span className={sidebarListMoreMenuLabelClassName}>{localize("com_knowledge.share")}</span>
                                        </DropdownMenuItem>
                                    )}
                                    {canManageMembers && (
                                        <DropdownMenuItem
                                            className={sidebarListMoreMenuItemClassName}
                                            onClick={() => setPermTarget({ id: space.id, name: space.name, type: "knowledge_space" })}
                                        >
                                            <Outlined.PeopleSafe className={sidebarListMoreMenuIconClassName} />
                                            <span className={sidebarListMoreMenuLabelClassName}>{localize("com_knowledge.member_management")}</span>
                                        </DropdownMenuItem>
                                    )}
                                    {canDeleteSpace && (
                                        <DropdownMenuItem className={sidebarListMoreMenuDangerItemClassName} onClick={() => onDeleteSpace?.()}>
                                            <Outlined.Delete className={sidebarListMoreMenuDangerIconClassName} />
                                            <span className={sidebarListMoreMenuDangerLabelClassName}>{localize("com_knowledge.delete_space")}</span>
                                        </DropdownMenuItem>
                                    )}
                                </SidebarListMoreMenuContent>
                            </DropdownMenu>
                        </div>
                    </div>
                </div>
            )}
            {/* Header (desktop only; on mobile these actions live in the top-bar menu) */}
            {!isH5 && (
            <div className="shrink-0">
            <KnowledgeSpaceHeader
                space={space}
                currentPath={currentPath}
                onNavigateFolder={onNavigateFolder}
                searchQuery={searchQuery}
                isSearching={isSearching}
                onSearch={handleSearch}
                viewMode={viewMode}
                setViewMode={setViewMode}
                enableCardMode={!isH5}
                statusFilter={statusFilter}
                onFilterStatus={handleStatusFilter}
                sortBy={sortBy}
                sortDirection={sortDirection}
                onSort={handleSort}
                onCreateFolder={onCreateFolder}
                onTriggerUpload={triggerUpload}
                onTriggerUploadFolder={triggerUploadFolder}
                canCreateFolder={canCreateFolder}
                canUploadFile={canUploadFile}
                supportedFormatsLabel={localize(
                    enableEtl4lm
                        ? "com_knowledge.supported_formats_with_etl4lm"
                        : "com_knowledge.supported_formats_basic"
                )}
                selectedCount={selectedFiles.size}
                hasFoldersSelected={hasFoldersSelected}
                hasFailedFiles={hasFailedFiles}
                onClearSelection={() => setSelectedFiles(new Set())}
                onBatchDownload={handleBatchDownload}
                canBatchDownload={canBatchDownload}
                onBatchTag={handleBatchTag}
                onBatchRetry={handleBatchRetry}
                onBatchMove={handleBatchMove}
                canBatchMove={canBatchMove}
                onBatchDelete={handleBatchDelete}
                canBatchDelete={canBatchDelete}
                onGoKnowledgeSquare={onGoKnowledgeSquare}
                canShareSpace={canShareSpace}
                versionManagementEnabled={versionManagementEnabled}
                hasSimilarSelected={hasSimilarSelected}
                onProcessSimilar={handleProcessSimilar}
                canManageMembers={canManageMembers}
            />
            </div>
            )}

            {/* Content Container：中间区域滚动；手机端分页栏在下方 shrink-0，不随列表滚走 */}
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                <div
                    className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-white"
                    onContextMenu={handleContentContextMenu}
                >
                    <DropdownMenu open={contextMenuOpen} onOpenChange={setContextMenuOpen}>
                        <DropdownMenuTrigger asChild>
                            <button
                                type="button"
                                aria-hidden="true"
                                tabIndex={-1}
                                className="fixed size-0 opacity-0"
                                style={{ left: contextMenuPosition.x, top: contextMenuPosition.y }}
                            />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className={knowledgeSpaceDropdownSurfaceClassName}>
                            <DropdownMenuItem onClick={onCreateFolder} className="cursor-pointer">
                                <FolderPlus className="mr-2 size-4" />
                                {localize("com_knowledge.new_folder")}
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                    {suppressList ? (
                        // Search page before any query — intentionally empty.
                        <div className="min-h-0 flex-1" />
                    ) : (loading && displayFiles.length === 0) ? (
                        // Space switching / first load: show a spinner instead of the
                        // "no files here" empty illustration. The fileManager hook clears
                        // `files` immediately on activeSpace change, so this branch fires
                        // for the entire fetch window — the right pane no longer keeps
                        // showing the previous space's contents while the API responds.
                        // A folder upload no longer hits this branch: its placeholder card
                        // lives in the grid (displayFiles), keeping the rest interactive.
                        <div className="flex h-full flex-1 flex-col items-center justify-center pb-[112px] pt-10 text-center">
                            <LoadingIcon className="size-20 text-primary" />
                        </div>
                    ) : displayFiles.length === 0 ? (
                        // pb-[112px] reserves room for the floating AI dock so the empty state
                        // centers in the visible region above it, matching the card grid.
                        <div className="flex h-full flex-1 flex-col items-center justify-center pb-[112px] pt-10 text-center">
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
                        <div ref={fileListScrollRevealRef} onScroll={handleListScroll} className="min-h-0 flex-1 overflow-y-auto scrollbar-on-scroll">
                            <div
                                ref={cardGridRef}
                                className={cn(
                                    // pb-[112px] reserves room for the bottom AI dock (40px gap + 56px input + 16px safe-area)
                                    // so the last card row clears the dock with a 40px visual gap above the input top.
                                    "w-full min-w-0 pt-4 pb-[112px]",
                                    effectiveViewMode === "list"
                                        ? "grid grid-cols-1 gap-0"
                                        : "grid gap-4"
                                )}
                                style={
                                    effectiveViewMode === "card"
                                        ? { gridTemplateColumns: `repeat(${cardCols}, minmax(0, 1fr))` }
                                        : undefined
                                }
                            >
                                {displayFiles.map((file) => (
                                    <div key={file.id} data-knowledge-file-item>
                                        <FileCard
                                            file={file}
                                            userRole={space.role}
                                            onEnsureFilePermissions={ensureFilePermissions}
                                            isSelected={selectedFiles.has(file.id)}
                                            onSelect={(selected) => handleSelectFile(file.id, selected)}
                                            onDownload={() => handleSingleDownload(file.id)}
                                            onRename={(newName) => onRenameFile(file.id, newName)}
                                            onMove={() => openMove([file])}
                                            canMove={file.type === FileType.FOLDER ? canMoveFolder : canMoveFile}
                                            onDelete={() => handleDelete(file.id)}
                                            onEditTags={() => handleOpenEditTags(file.id)}
                                            onRetry={() => handleSingleRetry(file.id)}
                                            onNavigateFolder={() => onNavigateFolder(file.id)}
                                            onPreview={handlePreviewFile}
                                            onValidateName={(newName) => validateFileName(newName, file.type === FileType.FOLDER, file.id, !!file.isCreating)}
                                            onCancelCreate={onCancelCreateFolder}
                                            onManagePermission={permissionEntryIds.has(file.id) ? () => handleManagePermission(file.id) : undefined}
                                            versionManagementEnabled={versionManagementEnabled}
                                            onOpenVersionManagement={(f) => setVersionMgmtFile(f)}
                                            onOpenVersionHistory={(f) => setVersionHistoryFile(f)}
                                            canManageMembers={canManageMembers}
                                            canRename={renameEntryIds.has(file.id)}
                                            canDelete={deleteEntryIds.has(file.id)}
                                            canDownload={downloadEntryIds.has(file.id)}
                                            mobileListMode={isH5}
                                            highlightedTagIds={searchTagIds}
                                            highlightKeyword={searchQuery}
                                            cardDraggable={cardDrag.enabled}
                                            onCardDragStart={cardDrag.handleDragStart(file)}
                                            isFolderDragOver={cardDrag.dragOverFolderId === file.id}
                                            onFolderDragOver={cardDrag.handleFolderDragOver(file)}
                                            onFolderDragLeave={cardDrag.handleFolderDragLeave(file)}
                                            onFolderDrop={cardDrag.handleFolderDrop(file)}
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>
                    ) : (
                        <div className="flex min-h-0 min-w-0 flex-1 flex-col pb-4">
                            <div ref={tableScrollRevealRef} className="flex min-h-0 min-w-0 flex-1 flex-col border-t border-[#e5e6eb]">
                                <FileTable files={displayFiles}
                                    onEnsureFilePermissions={ensureFilePermissions}
                                    onScroll={handleListScroll}
                                    /* Reserve 112px under the last row so the bottom AI dock leaves
                                       a 40px visual gap above the input. */
                                    bottomSpacing={112}
                                    selectedFiles={selectedFiles}
                                    handleSelectAll={handleSelectAll}
                                    handleSelectFile={handleSelectFile}
                                    isAdmin={isAdmin}
                                    currentUserRole={space.role}
                                    onDownload={(id) => handleSingleDownload(id)}
                                    onEditTags={(id) => handleOpenEditTags(id)}
                                    onRename={(id, newName) => onRenameFile(id, newName)}
                                    onMove={(file) => openMove([file])}
                                    canMoveFile={canMoveFile}
                                    canMoveFolder={canMoveFolder}
                                    onMoveToFolder={canUploadFile ? (folderId, items, folderName) => dropMoveToFolder(items, folderId, folderName) : undefined}
                                    onDelete={(id) => handleDelete(id)}
                                    onRetry={(id) => handleSingleRetry(id)}
                                    onNavigateFolder={(id) => onNavigateFolder(id)}
                                    onPreview={(id) => handlePreviewFile(id)}
                                    onValidateName={validateFileName}
                                    onCancelCreate={onCancelCreateFolder}
                                    permissionEntryIds={permissionEntryIds}
                                    renameEntryIds={renameEntryIds}
                                    deleteEntryIds={deleteEntryIds}
                                    downloadEntryIds={downloadEntryIds}
                                    onManagePermission={handleManagePermission}
                                    versionManagementEnabled={versionManagementEnabled}
                                    onOpenVersionManagement={(f) => setVersionMgmtFile(f)}
                                    onOpenVersionHistory={(f) => setVersionHistoryFile(f)}
                                    canManageMembers={canManageMembers}
                                    sortBy={sortBy}
                                    sortDirection={sortDirection}
                                    onSort={handleSort}
                                    highlightedTagIds={searchTagIds}
                                    highlightKeyword={searchQuery}
                                />
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Footer：仅在搜索且有选中时展示所选文件的路径面包屑（无分页器） */}
            {!isH5 && isSearching && selectedFiles.size > 0 && (
                <div className="mt-auto w-full min-w-0 shrink-0">
                    <div className="flex w-full min-w-0 flex-shrink-0 items-center gap-y-1 border-t border-[#e5e6eb] bg-white py-3">
                        <SelectionPathBreadcrumb
                            spaceId={space.id}
                            spaceName={space.name}
                            selectedFiles={selectedFiles}
                            displayFiles={displayFiles}
                        />
                    </div>
                </div>
            )}

            {/* Mobile batch action bar — pinned to the bottom, replaces the AI dock while
                files are selected. Actions + permissions mirror the desktop toolbar. */}
            {selectionActive && batchActions.length > 0 && (
                /* Floating capsule: 16px from left/right/bottom, 12px inner padding. Buttons share
                   width evenly (flex-1); a 12px-tall divider sits between them. */
                <div className="absolute inset-x-0 bottom-[max(16px,env(safe-area-inset-bottom))] z-30 px-4">
                    <div className="flex w-full items-center rounded-[20px] border border-[#EBECF0] bg-white p-3 shadow-[0_6px_24px_0_rgba(0,17,147,0.12)]">
                        {inlineActions.map((a, i) => (
                            <Fragment key={a.key}>
                                {i > 0 && <span className="h-3 w-px shrink-0 bg-[#EBECF0]" aria-hidden />}
                                <button
                                    type="button"
                                    onClick={a.onClick}
                                    className={cn(
                                        "flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap px-4 py-[5px] text-sm",
                                        a.danger ? "text-[#F53F3F]" : "text-[#212121]",
                                    )}
                                >
                                    <a.Icon className="size-4" />
                                    {a.label}
                                </button>
                            </Fragment>
                        ))}
                        {overflowActions.length > 0 && (
                            <>
                                {inlineActions.length > 0 && <span className="h-3 w-px shrink-0 bg-[#EBECF0]" aria-hidden />}
                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <button
                                            type="button"
                                            className="flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap px-4 py-[5px] text-sm text-[#212121]"
                                        >
                                            <Outlined.More className="size-4" />
                                            {localize("com_knowledge.more")}
                                        </button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent side="top" align="end" className={knowledgeSpaceDropdownSurfaceClassName}>
                                        {overflowActions.map((a) => (
                                            <DropdownMenuItem
                                                key={a.key}
                                                onClick={a.onClick}
                                                className={a.danger ? sidebarListMoreMenuDangerItemClassName : sidebarListMoreMenuItemClassName}
                                            >
                                                <a.Icon className={a.danger ? sidebarListMoreMenuDangerIconClassName : sidebarListMoreMenuIconClassName} />
                                                <span className={a.danger ? sidebarListMoreMenuDangerLabelClassName : sidebarListMoreMenuLabelClassName}>{a.label}</span>
                                            </DropdownMenuItem>
                                        ))}
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </>
                        )}
                    </div>
                </div>
            )}

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
                    isDepartmentSpace={permTarget.type === "knowledge_space" && space?.spaceKind === "department"}
                />
            )}

            {/* F034: Move files/folders (same-space + cross-space) */}
            <MoveToDialog
                open={moveDialogOpen}
                onOpenChange={setMoveDialogOpen}
                currentSpaceId={space.id}
                currentSpaceName={space.name}
                onConfirm={handleMoveConfirm}
            />

            {versionManagementEnabled && (
                <>
                    <VersionManagementDialog
                        open={versionMgmtFile !== null}
                        onOpenChange={(o) => { if (!o) setVersionMgmtFile(null); }}
                        spaceId={spaceIdNum}
                        file={versionMgmtFile}
                        onLinked={() => {
                            handleVersionAction();
                            setVersionMgmtFile(null);
                        }}
                    />
                    <VersionHistorySheet
                        open={versionHistoryFile !== null}
                        onOpenChange={(o) => { if (!o) setVersionHistoryFile(null); }}
                        fileId={versionHistoryFile ? Number(versionHistoryFile.id) : null}
                        documentTitle={versionHistoryFile?.name}
                        canManage={isAdmin}
                        onPreview={(versionFileId, fileName) => handlePreviewFile(String(versionFileId), fileName)}
                        onDownload={async (versionFileId, fileName) => {
                            try {
                                const downloadData = await getFileDownloadApi(
                                    String(space.id),
                                    String(versionFileId),
                                );
                                const downloadUrl = downloadData.original_url;
                                if (!downloadUrl) {
                                    showToast({
                                        message: localize("com_knowledge.get_download_link_failed"),
                                        status: "error",
                                    });
                                    return;
                                }
                                triggerUrlDownload(downloadUrl, fileName);
                            } catch {
                                showToast({
                                    message: localize("com_knowledge.download_failed"),
                                    status: "error",
                                });
                            }
                        }}
                        onPrimaryChanged={handleVersionAction}
                        onDeleted={handleVersionAction}
                    />
                    <SimilarDocumentDialog
                        open={similarDialogOpen}
                        onOpenChange={(o) => { setSimilarDialogOpen(o); if (!o) setSimilarRestrictIds([]); }}
                        spaceId={spaceIdNum}
                        restrictToFileIds={similarRestrictIds}
                        onProcessed={handleVersionAction}
                    />
                </>
            )}
        </div>
    );
}
