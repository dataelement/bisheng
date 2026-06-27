import { useState, useRef, useEffect, useLayoutEffect, useMemo, type MouseEvent, type ReactNode } from "react";
import { useRecoilValue } from "recoil";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderPlus, Loader2 } from "lucide-react";
import { FileStatus, FileType, KnowledgeFile, KnowledgeSpace, SortDirection, SortType, SpaceLevel, SpaceRole, batchDeleteApi, batchDownloadApi, batchRetryApi, getFileDownloadApi, getPendingSimilarFilesApi, importWebLinkApi } from "~/api/knowledge";
import { useConfirm, useToastContext } from "~/Providers";
import { useVersionManagementEnabled } from "~/hooks";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Button,
    Input,
} from "~/components/ui";
import { useFileDragDrop } from "../hooks/useFileDragDrop";
import {
    MAX_FOLDER_UPLOAD_COUNT,
    MAX_UPLOAD_COUNT,
    getAllowedExtensions,
    getFileInputAccept,
    getMaxFileSizeBytesForFile,
    getMaxFileSizeMBForFile,
    resolveUploadSizeLimits,
    triggerUrlDownload,
} from "../knowledgeUtils";
import { bishengConfState } from "~/pages/appChat/store/atoms";
import { SearchParams } from "./CompoundSearchInput";
import { EditTagsModal } from "./EditTagsModal";
import { FileCard } from "./FileCard";
import { FilePublishDialog } from "./FilePublishDialog";
import { FileTable } from "./FileTable";
import { KnowledgeSpaceHeader } from "./KnowledgeSpaceHeader";
import { KnowledgeSpaceShareDialog } from "./KnowledgeSpaceShareDialog";
import { LoadMore } from "./LoadMore";
import { SelectionPathBreadcrumb } from "./SelectionPathBreadcrumb";
import { VersionManagementDialog } from "./VersionManagementDialog";
import { VersionHistorySheet } from "./VersionHistorySheet";
import { SimilarDocumentDialog } from "./SimilarDocumentDialog";
import { MoveFolderDialog } from "./MoveFolderDialog";
import { canOpenPermissionDialog, checkPermission } from "~/api/permission";
import {
    hasKnowledgeSpacePermission,
    useKnowledgeSpaceActionPermissions,
} from "../hooks/useKnowledgeSpacePermissions";
import { useLocalize, usePrefersMobileLayout, useScrollRevealRef } from "~/hooks";
import { knowledgeSpaceDropdownSurfaceClassName } from "~/components/SidebarListMoreMenu";
import { cn, getFullWidthLength } from "~/utils";
import type { PortalFileCategoryOption } from "../portal/types";

const WEB_LINK_DUPLICATE_ERROR_CODES = new Set([18021, 18023]);

interface KnowledgeSpaceContentProps {
    space: KnowledgeSpace;
    files: KnowledgeFile[];
    currentPage: number;
    pageSize: number;
    total: number;
    /** F027 §AC-17-client-补做: whether a next batch exists; drives LoadMore sentinel. */
    hasMore: boolean;
    onPageChange: (page: number) => void;
    loading: boolean;
    onSearch: (params: SearchParams) => void;
    onFilterStatus: (status: FileStatus[]) => void;
    onSort: (sortBy: SortType | undefined, direction: SortDirection | undefined) => void;
    onNavigateFolder: (folderId?: string) => void;
    onUploadFile: (files?: FileList | File[]) => void;
    onUploadFolder: (
        files: FileList | File[],
        options: { allowedExtensions: readonly string[]; limits: import("../knowledgeUtils").UploadSizeLimits },
    ) => void;
    onCreateFolder: () => void;
    onDownloadFile: (fileId: string) => void;
    onRenameFile: (fileId: string, newName: string) => void;
    onDeleteFile: (fileId: string) => void;
    onEditTags: (fileId: string) => void;
    onRetryFile: (fileId: string) => void;
    onMoveFile?: (fileId: string, targetFolderId: number | null) => void;
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
    onPreviewFile?: (file: KnowledgeFile) => void;
    afterSearchActions?: ReactNode;
    hideNativeAddMenu?: boolean;
    hideNativeStatusFilter?: boolean;
    hideShareButton?: boolean;
    hideFilePermissionActions?: boolean;
    enableEncodingClassification?: boolean;
    fileCategoryOptions?: PortalFileCategoryOption[];
    encodingPrefix?: string;
    markPendingDeletion: (ids: Array<string | number>) => void;
    clearPendingDeletion: (ids: Array<string | number>) => void;
    setFiles: React.Dispatch<React.SetStateAction<KnowledgeFile[]>>;
    setTotal: React.Dispatch<React.SetStateAction<number>>;
}

export function KnowledgeSpaceContent({
    space,
    files,
    currentPage,
    pageSize,
    total,
    hasMore,
    onPageChange,
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
    onEditTags,
    onRetryFile,
    onMoveFile,
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
    onPreviewFile,
    afterSearchActions,
    hideNativeAddMenu,
    hideNativeStatusFilter,
    hideShareButton = false,
    hideFilePermissionActions = false,
    enableEncodingClassification = false,
    fileCategoryOptions = [],
    encodingPrefix,
    markPendingDeletion,
    clearPendingDeletion,
    setFiles,
    setTotal,
}: KnowledgeSpaceContentProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const fileListScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
    const tableScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
    const normalizeParentId = (id?: string | number | null) =>
        id === undefined || id === null || id === "" ? undefined : String(id);
    const isCurrentSpaceFile = (file: KnowledgeFile) =>
        !file.spaceId || String(file.spaceId) === String(space.id);
    const isCurrentFolderTransientFile = (file: KnowledgeFile) =>
        normalizeParentId(file.parentId) === normalizeParentId(currentFolderId);
    const transientFiles = [
        ...(creatingFolder ? [creatingFolder] : []),
        ...uploadingFiles,
    ].filter((file) => isCurrentSpaceFile(file) && isCurrentFolderTransientFile(file));
    const uploadingNames = new Set(
        transientFiles
            .filter((file) => file.status === FileStatus.UPLOADING)
            .map((file) => file.name),
    );
    const displayFiles = [
        ...transientFiles,
        ...files.filter((file) => isCurrentSpaceFile(file) && !uploadingNames.has(file.name)),
    ];

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
    const [violationFile, setViolationFile] = useState<KnowledgeFile | null>(null);
    const [isBatchTagging, setIsBatchTagging] = useState(false);
    const [contextMenuOpen, setContextMenuOpen] = useState(false);
    const [contextMenuPosition, setContextMenuPosition] = useState({ x: 0, y: 0 });

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
    }, [viewMode, displayFiles.length, isAiAssistantOpen]);

    useEffect(() => {
        setSelectedFiles(new Set());
        setSearchQuery("");
        setSearchTagIds([]); // 切换空间时清空搜索条件
    }, [space.id]);

    const isAdmin = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;

    const { permissions: spaceActionPermissions } = useKnowledgeSpaceActionPermissions(
        [space.id],
        { fullAccessSpaceIds: isAdmin ? [space.id] : [] },
    );
    // Version-management write entries (process-similar button, list "similar"
    // pill) gate on the user's OpenFGA relation to this space: creator (owner)
    // or manager. We can't trust `space.role === ADMIN` alone because shared
    // spaces can return a stale SpaceChannelMember.user_role for users whose
    // real grant lives only in OpenFGA. checkPermission(..., "manager") covers
    // both owner and manager — OpenFGA's owner ⊃ manager makes owners allowed too.
    const { data: spaceManageCheck } = useQuery({
        queryKey: ["space-manage-check", space.id],
        queryFn: () => checkPermission("knowledge_space", space.id, "manager"),
        enabled: !!space.id,
    });
    const canManageMembers = space.role === SpaceRole.CREATOR
        || Boolean(spaceManageCheck?.allowed);

    // ─── Version Management ──────────────────────────────────────────────
    const versionManagementEnabled = useVersionManagementEnabled();
    const queryClient = useQueryClient();
    const spaceIdNum = Number(space.id);

    const [versionMgmtFile, setVersionMgmtFile] = useState<KnowledgeFile | null>(null);
    const [versionHistoryFile, setVersionHistoryFile] = useState<KnowledgeFile | null>(null);
    const [similarDialogOpen, setSimilarDialogOpen] = useState(false);

    const { data: pendingSimilarList = [] } = useQuery({
        queryKey: ["pending-similar", spaceIdNum],
        queryFn: () => getPendingSimilarFilesApi(spaceIdNum),
        enabled: versionManagementEnabled && spaceIdNum > 0 && canManageMembers,
    });
    const pendingSimilarCount = pendingSimilarList.length;

    // SimHash scan runs asynchronously on the backend after a file's parse finishes,
    // so files can transition has_similar=false → true outside our polling cadence
    // for pending-similar. Watch the has_similar id set on the visible file list AND
    // the total file count — the latter catches cross-folder deletions (e.g.
    // deleting a folder whose children carry similar marks) where the visible
    // displayFiles slice doesn't see the cascaded removals.
    const similarFileIdsKey = displayFiles
        .filter((f) => f.has_similar && !f.is_multi_version)
        .map((f) => f.id)
        .sort()
        .join(",");
    useEffect(() => {
        if (!versionManagementEnabled || spaceIdNum <= 0) return;
        queryClient.invalidateQueries({ queryKey: ["pending-similar", spaceIdNum] });
    }, [similarFileIdsKey, total, versionManagementEnabled, spaceIdNum, queryClient]);

    // Invalidate pending-similar and trigger file list refresh after any version action
    const handleVersionAction = () => {
        queryClient.invalidateQueries({ queryKey: ["pending-similar", spaceIdNum] });
        queryClient.invalidateQueries({ queryKey: ["file-versions"] });
        // Signal parent to reload file list (same pattern used by batch delete/retry)
        onDeleteFile("");
    };

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
    const [renameEntryIds, setRenameEntryIds] = useState<Set<string>>(new Set());
    const [deleteEntryIds, setDeleteEntryIds] = useState<Set<string>>(new Set());
    const [downloadEntryIds, setDownloadEntryIds] = useState<Set<string>>(new Set());
    const [publishEntryIds, setPublishEntryIds] = useState<Set<string>>(new Set());
    const [publishingFile, setPublishingFile] = useState<KnowledgeFile | null>(null);
    const [movingFile, setMovingFile] = useState<KnowledgeFile | null>(null);
    const permissionEntryProbeKey = displayFiles
        .filter((file) => !file.isCreating && /^\d+$/.test(String(file.id)))
        .map((file) => `${file.id}:${file.type}`)
        .join("|");
    const visiblePermissionEntryIds = useMemo(
        () => hideFilePermissionActions ? new Set<string>() : permissionEntryIds,
        [hideFilePermissionActions, permissionEntryIds],
    );
    const canUseAddActions = canCreateFolder && !isSearching;

    const { showToast } = useToastContext();
    const confirm = useConfirm();

    useEffect(() => {
        if (isAdmin) {
            setCanCreateFolder(true);
            setCanUploadFile(true);
            return;
        }

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
    }, [currentFolderId, isAdmin, space.id]);

    useEffect(() => {
        let cancelled = false;
        const controller = new AbortController();
        const candidates = displayFiles.filter(
            (file) => !file.isCreating && /^\d+$/.test(String(file.id))
        );

        if (hideFilePermissionActions) {
            setPermissionEntryIds(new Set());
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

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
        hideFilePermissionActions,
        isAdmin,
        permissionEntryProbeKey,
    ]);

    useEffect(() => {
        let cancelled = false;
        const controller = new AbortController();
        const candidates = displayFiles.filter(
            (file) => !file.isCreating && /^\d+$/.test(String(file.id))
        );

        if (isAdmin) {
            setRenameEntryIds(new Set(candidates.map((file) => file.id)));
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

        if (candidates.length === 0) {
            setRenameEntryIds(new Set());
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

        Promise.all(
            candidates.map(async (file) => {
                const resourceType = file.type === FileType.FOLDER ? "folder" : "knowledge_file";
                const result = await checkPermission(
                    resourceType,
                    file.id,
                    "can_edit",
                    file.type === FileType.FOLDER ? "rename_folder" : "rename_file",
                    { signal: controller.signal },
                ).catch(() => ({ allowed: false }));
                return result.allowed ? file.id : null;
            })
        ).then((ids) => {
            if (!cancelled) {
                setRenameEntryIds(new Set(ids.filter((id): id is string => Boolean(id))));
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [isAdmin, permissionEntryProbeKey]);

    useEffect(() => {
        let cancelled = false;
        const controller = new AbortController();
        const candidates = displayFiles.filter(
            (file) => !file.isCreating && /^\d+$/.test(String(file.id))
        );

        if (isAdmin) {
            setDownloadEntryIds(new Set(candidates.map((file) => file.id)));
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

        if (candidates.length === 0) {
            setDownloadEntryIds(new Set());
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

        Promise.all(
            candidates.map(async (file) => {
                const resourceType = file.type === FileType.FOLDER ? "folder" : "knowledge_file";
                const result = await checkPermission(
                    resourceType,
                    file.id,
                    "can_read",
                    file.type === FileType.FOLDER ? "download_folder" : "download_file",
                    { signal: controller.signal },
                ).catch(() => ({ allowed: false }));
                return result.allowed ? file.id : null;
            })
        ).then((ids) => {
            if (!cancelled) {
                setDownloadEntryIds(new Set(ids.filter((id): id is string => Boolean(id))));
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [isAdmin, permissionEntryProbeKey]);

    useEffect(() => {
        let cancelled = false;
        const controller = new AbortController();
        const candidates = displayFiles.filter(
            (file) => !file.isCreating && /^\d+$/.test(String(file.id))
        );

        if (isAdmin) {
            setDeleteEntryIds(new Set(candidates.map((file) => file.id)));
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

        if (candidates.length === 0) {
            setDeleteEntryIds(new Set());
            return () => {
                cancelled = true;
                controller.abort();
            };
        }

        Promise.all(
            candidates.map(async (file) => {
                const resourceType = file.type === FileType.FOLDER ? "folder" : "knowledge_file";
                const result = await checkPermission(
                    resourceType,
                    file.id,
                    "can_delete",
                    file.type === FileType.FOLDER ? "delete_folder" : "delete_file",
                    { signal: controller.signal },
                ).catch(() => ({ allowed: false }));
                return result.allowed ? file.id : null;
            })
        ).then((ids) => {
            if (!cancelled) {
                setDeleteEntryIds(new Set(ids.filter((id): id is string => Boolean(id))));
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [isAdmin, permissionEntryProbeKey]);

    useEffect(() => {
        const eligibleSourceSpace = space.spaceLevel !== SpaceLevel.PUBLIC;
        const candidates = displayFiles.filter((file) => (
            eligibleSourceSpace &&
            !file.isCreating &&
            file.type !== FileType.FOLDER &&
            file.status === FileStatus.SUCCESS &&
            /^\d+$/.test(String(file.id))
        ));

        if (!eligibleSourceSpace || candidates.length === 0) {
            setPublishEntryIds(new Set());
            return;
        }

        if (isAdmin) {
            setPublishEntryIds(new Set(candidates.map((file) => file.id)));
            return;
        }

        let cancelled = false;
        const controller = new AbortController();
        checkPermission(
            "knowledge_space",
            space.id,
            "can_edit",
            "upload_file",
            { signal: controller.signal },
        ).catch(() => ({ allowed: false })).then((result) => {
            if (!cancelled) {
                setPublishEntryIds(result.allowed ? new Set(candidates.map((file) => file.id)) : new Set());
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [isAdmin, permissionEntryProbeKey, space.id, space.spaceLevel]);

    // Read max file size from env config (MB), fallback to default 200MB
    const bishengConfig = useRecoilValue(bishengConfState);
    const uploadSizeLimits = useMemo(
        () => resolveUploadSizeLimits(bishengConfig ?? undefined),
        [bishengConfig],
    );
    const enableEtl4lm = bishengConfig?.enable_etl4lm ?? false;
    const allowedExtensions = getAllowedExtensions(enableEtl4lm);
    const fileInputAccept = getFileInputAccept(enableEtl4lm);

    // ─── File Upload Trigger ─────────────────────────────────────────────
    const fileInputRef = useRef<HTMLInputElement>(null);
    const folderInputRef = useRef<HTMLInputElement>(null);
    const [webLinkDialogOpen, setWebLinkDialogOpen] = useState(false);
    const [webLinkUrl, setWebLinkUrl] = useState("");
    const [webLinkTitle, setWebLinkTitle] = useState("");
    const [webLinkSubmitting, setWebLinkSubmitting] = useState(false);

    const triggerUpload = () => {
        if (!canUploadFile) return;
        fileInputRef.current?.click();
    };

    const triggerUploadFolder = () => {
        if (!canUploadFile) return;
        folderInputRef.current?.click();
    };

    const triggerWebLink = () => {
        if (!canUploadFile) return;
        setWebLinkDialogOpen(true);
    };

    const isWebLinkDuplicateError = (error: any) => WEB_LINK_DUPLICATE_ERROR_CODES.has(Number(error?.status_code));

    const submitWebLink = async (overwrite = false) => {
        const created = await importWebLinkApi(space.id, {
            url: webLinkUrl.trim(),
            title: webLinkTitle.trim() || undefined,
            parent_id: currentFolderId ? Number(currentFolderId) : null,
            ...(overwrite ? { overwrite: true } : {}),
        });
        setFiles((prev) => [
            created,
            ...prev.filter((file) => (
                file.id !== created.id
                && file.name !== created.name
                && file.sourceUrl !== created.sourceUrl
            )),
        ]);
        setTotal((prev) => prev + (overwrite ? 0 : 1));
        setWebLinkUrl("");
        setWebLinkTitle("");
        setWebLinkDialogOpen(false);
        showToast({ message: "网页链接已开始导入", status: "success" });
    };

    const handleSubmitWebLink = async () => {
        const normalizedUrl = webLinkUrl.trim();
        if (!normalizedUrl) {
            showToast({ message: "请输入网页链接", status: "error" });
            return;
        }
        try {
            const parsed = new URL(normalizedUrl);
            if (!["http:", "https:"].includes(parsed.protocol)) {
                showToast({ message: "仅支持 http 或 https 链接", status: "error" });
                return;
            }
        } catch {
            showToast({ message: "请输入有效的网页链接", status: "error" });
            return;
        }

        setWebLinkSubmitting(true);
        try {
            await submitWebLink();
        } catch (error: any) {
            if (isWebLinkDuplicateError(error)) {
                const shouldOverwrite = await confirm({
                    title: "发现重复网页链接",
                    description: webLinkTitle.trim() || normalizedUrl,
                    cancelText: "取消",
                    confirmText: "覆盖",
                });
                if (shouldOverwrite) {
                    setWebLinkDialogOpen(false);
                    try {
                        await submitWebLink(true);
                    } catch (overwriteError: any) {
                        showToast({ message: overwriteError?.message || "网页链接覆盖失败", status: "error" });
                    }
                } else {
                    setWebLinkUrl("");
                    setWebLinkTitle("");
                    setWebLinkDialogOpen(false);
                }
                return;
            }
            showToast({ message: error?.message || "网页链接导入失败", status: "error" });
        } finally {
            setWebLinkSubmitting(false);
        }
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

            if (filesList.length > MAX_UPLOAD_COUNT) {
                showToast({ message: localize("com_knowledge.max_upload_50"), status: "error" });
                if (fileInputRef.current) fileInputRef.current.value = "";
                return;
            }

            for (let f of filesList) {
                if (f.size > getMaxFileSizeBytesForFile(f.name, uploadSizeLimits)) {
                    showToast({
                        message: localize("com_knowledge.file_exceeds_limit", {
                            name: f.name,
                            size: getMaxFileSizeMBForFile(f.name, uploadSizeLimits),
                        }),
                        status: "error",
                    });
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

    // Folder upload: hand the full FileList over to the hook, which handles
    // hidden-folder rejection, dup-name check, count cap, and silent filtering.
    const handleFolderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const filesList = e.target.files;
        if (filesList && filesList.length > 0 && canUploadFile) {
            onUploadFolder(filesList, {
                allowedExtensions,
                limits: uploadSizeLimits,
            });
        }
        if (folderInputRef.current) folderInputRef.current.value = "";
    };

    // ─── Drag and drop ──────────────────────────────────────────────────
    const { handleDragEnter, handleDragLeave, handleDragOver, handleDrop } = useFileDragDrop({
        onDragStateChange,
        onUploadFile: canUploadFile ? onUploadFile : () => undefined,
        uploadSizeLimits,
        enableEtl4lm,
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

    const handlePreviewFile = (fileId: string, nameOverride?: string) => {
        const file = displayFiles.find(f => f.id === fileId);
        if (file?.status === FileStatus.VIOLATION) {
            setViolationFile(file);
            return;
        }
        if (file && onPreviewFile) {
            onPreviewFile(file);
            return;
        }
        const fileName = nameOverride || file?.name || localize("com_knowledge.unknown_file");
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
        const allIds = selectedList.map(f => f.id);
        const removeCount = allIds.length;

        // Optimistic: drop selected rows immediately + mark to suppress poll ghosts.
        markPendingDeletion(allIds);
        setFiles(prev => prev.filter(f => !selectedFiles.has(f.id)));
        setTotal(prev => Math.max(0, prev - removeCount));
        setSelectedFiles(new Set());
        showToast({ message: localize("com_knowledge.batch_delete_success"), status: "success" });

        try {
            await batchDeleteApi(space.id, {
                file_ids: fileIds.length ? fileIds : undefined,
                folder_ids: folderIds.length ? folderIds : undefined,
            });
        } catch {
            showToast({ message: localize("com_knowledge.batch_delete_failed"), status: "error" });
            clearPendingDeletion(allIds);
            onDeleteFile("");
            return;
        }
        clearPendingDeletion(allIds);
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
    const canBatchDelete = selectedList.length > 0 && selectedList.every((file) =>
        deleteEntryIds.has(file.id)
    );
    const canBatchDownload = selectedList.length > 0 && selectedList.every((file) =>
        downloadEntryIds.has(file.id)
    );

    return (
        <div
            className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-hidden rounded-lg px-4 max-[767px]:overflow-hidden"
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
            {/* Hidden Folder Input — `webkitdirectory` makes the picker select
                a directory instead of files; each File carries its
                `webkitRelativePath`. No `accept` here: filtering by extension
                is done in the hook (silently) per spec. */}
            <input
                type="file"
                multiple
                className="hidden"
                ref={folderInputRef}
                onChange={handleFolderChange}
                // `webkitdirectory`/`directory` are non-standard but accepted
                // by every browser we ship to. React typings don't list them.
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                {...({ webkitdirectory: "", directory: "" } as any)}
            />
            {/* Header */}
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
                onTriggerWebLink={triggerWebLink}
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
                onBatchDelete={handleBatchDelete}
                canBatchDelete={canBatchDelete}
                onGoKnowledgeSquare={onGoKnowledgeSquare}
                onToggleAiAssistant={onToggleAiAssistant}
                isAiAssistantOpen={isAiAssistantOpen}
                canShareSpace={!hideShareButton && canShareSpace}
                afterSearchActions={afterSearchActions}
                hideNativeAddMenu={hideNativeAddMenu}
                hideNativeStatusFilter={hideNativeStatusFilter}
                versionManagementEnabled={versionManagementEnabled}
                pendingSimilarCount={pendingSimilarCount}
                onProcessSimilar={() => setSimilarDialogOpen(true)}
                canManageMembers={canManageMembers}
            />
            </div>

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
                    {loading && displayFiles.length === 0 ? (
                        <div className="flex h-full flex-1 items-center justify-center py-10 text-[#86909C]">
                            <Loader2 className="mr-2 size-4 animate-spin" />
                            <span className="text-[14px] leading-6">{localize("com_knowledge.loading")}</span>
                        </div>
                    ) : displayFiles.length === 0 ? (
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
                        <div ref={fileListScrollRevealRef} className="min-h-0 flex-1 overflow-y-auto scrollbar-on-scroll">
                            <div
                                ref={cardGridRef}
                                className={cn(
                                    "w-full min-w-0 py-4",
                                    viewMode === "list"
                                        ? "grid grid-cols-1 gap-2"
                                        : "grid gap-4"
                                )}
                                style={
                                    viewMode === "card"
                                        ? { gridTemplateColumns: `repeat(${cardCols}, minmax(0, 1fr))` }
                                        : undefined
                                }
                            >
                                {displayFiles.map((file) => (
                                    <div key={file.id} data-knowledge-file-item>
                                        <FileCard
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
                                            onManagePermission={visiblePermissionEntryIds.has(file.id) ? () => handleManagePermission(file.id) : undefined}
                                            canRename={renameEntryIds.has(file.id)}
                                            canDelete={deleteEntryIds.has(file.id)}
                                            canDownload={downloadEntryIds.has(file.id)}
                                            canPublish={publishEntryIds.has(file.id)}
                                            onPublishFile={setPublishingFile}
                                            mobileListMode={isH5 && viewMode === "list"}
                                            versionManagementEnabled={versionManagementEnabled}
                                            onOpenVersionManagement={(f) => setVersionMgmtFile(f)}
                                            onOpenVersionHistory={(f) => setVersionHistoryFile(f)}
                                            canManageMembers={canManageMembers}
                                        />
                                    </div>
                                ))}
                            </div>
                            {hasMore && (
                                <LoadMore
                                    onLoad={() => onPageChange(currentPage + 1)}
                                    loading={loading}
                                />
                            )}
                        </div>
                    ) : (
                        <div className="flex min-h-0 min-w-0 flex-1 flex-col pb-4">
                            <div ref={tableScrollRevealRef} className="min-h-0 min-w-0 flex-1 overflow-y-auto scrollbar-on-scroll border-t border-[#e5e6eb]">
                                <FileTable files={displayFiles}
                                    selectedFiles={selectedFiles}
                                    handleSelectAll={handleSelectAll}
                                    handleSelectFile={handleSelectFile}
                                    isAdmin={isAdmin}
                                    currentUserRole={space.role}
                                    onDownload={(id) => handleSingleDownload(id)}
                                    onEditTags={(id) => handleOpenEditTags(id)}
                                    onRename={(id, newName) => onRenameFile(id, newName)}
                                    onDelete={(id) => handleDelete(id)}
                                    onRetry={(id) => handleSingleRetry(id)}
                                    onNavigateFolder={(id) => onNavigateFolder(id)}
                                    onPreview={(id) => handlePreviewFile(id)}
                                    onValidateName={validateFileName}
                                    onCancelCreate={onCancelCreateFolder}
                                    permissionEntryIds={visiblePermissionEntryIds}
                                    renameEntryIds={renameEntryIds}
                                    deleteEntryIds={deleteEntryIds}
                                    downloadEntryIds={downloadEntryIds}
                                    publishEntryIds={publishEntryIds}
                                    onManagePermission={hideFilePermissionActions ? undefined : handleManagePermission}
                                    onMove={onMoveFile ? (file) => setMovingFile(file) : undefined}
                                    moveEntryIds={renameEntryIds}
                                    onPublishFile={setPublishingFile}
                                    sortBy={sortBy}
                                    sortDirection={sortDirection}
                                    onSort={handleSort}
                                    versionManagementEnabled={versionManagementEnabled}
                                    onOpenVersionManagement={(f) => setVersionMgmtFile(f)}
                                    onOpenVersionHistory={(f) => setVersionHistoryFile(f)}
                                    canManageMembers={canManageMembers}
                                    enableEncodingClassification={enableEncodingClassification}
                                    fileCategoryOptions={fileCategoryOptions}
                                    encodingPrefix={encodingPrefix}
                                    onFileEncodingUpdated={(fileId, newEncoding) => {
                                        setFiles((prev) => prev.map((file) => (
                                            file.id === fileId ? { ...file, fileEncoding: newEncoding } : file
                                        )));
                                    }}
                                />
                                {hasMore && (
                                    <LoadMore
                                        onLoad={() => onPageChange(currentPage + 1)}
                                        loading={loading}
                                    />
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Footer：与上方同宽（外层 px-4）；桌面 mt-auto；手机列表区内置底栏，随面板高度固定可见 */}
            <div
                className={cn(
                    "w-full min-w-0 shrink-0 max-[767px]:pb-[env(safe-area-inset-bottom,0px)]",
                    !isH5 && "mt-auto",
                )}
            >
                <div
                    className={cn(
                        "flex w-full min-w-0 flex-shrink-0 flex-wrap items-center justify-between gap-y-1 py-3",
                        isH5 && "flex-nowrap justify-end",
                        !isH5 && "border-t border-[#e5e6eb] bg-white",
                    )}
                >
                    {!isH5 && (
                        isSearching && selectedFiles.size > 0 ? (
                            <SelectionPathBreadcrumb
                                spaceId={space.id}
                                spaceName={space.name}
                                selectedFiles={selectedFiles}
                                displayFiles={displayFiles}
                            />
                        ) : (
                            <div />
                        )
                    )}

                    {/* F027 §AC-17-client-补做: PaginationBar removed; infinite scroll via <LoadMore /> sentinel inside the scroll containers above. */}
                </div>
            </div>

            <FilePublishDialog
                open={Boolean(publishingFile)}
                activeSpace={space}
                file={publishingFile}
                versionManagementEnabled={versionManagementEnabled}
                onOpenChange={(open) => {
                    if (!open) setPublishingFile(null);
                }}
            />

            {/* Move file/folder dialog */}
            {movingFile && (
                <MoveFolderDialog
                    open={Boolean(movingFile)}
                    spaceId={String(space.id)}
                    movingItemId={movingFile.id}
                    movingItemType={movingFile.type === FileType.FOLDER ? "folder" : "file"}
                    onConfirm={(targetFolderId) => {
                        onMoveFile?.(movingFile.id, targetFolderId);
                        setMovingFile(null);
                    }}
                    onCancel={() => setMovingFile(null)}
                />
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

            <Dialog open={!!violationFile} onOpenChange={(open) => {
                if (!open) setViolationFile(null);
            }}>
                <DialogContent className="max-w-[520px]">
                    <DialogHeader>
                        <DialogTitle>
                            {localize("com_knowledge.sensitive_violation_title")}
                        </DialogTitle>
                    </DialogHeader>
                    <div className="text-sm text-[#1d2129]">
                        <div className="rounded-md bg-[#fff2f0] px-3 py-2 text-[#f53f3f]">
                            {violationFile?.errorMessage || localize("com_knowledge.sensitive_violation_message")}
                        </div>
                    </div>
                </DialogContent>
            </Dialog>

            <Dialog open={webLinkDialogOpen} onOpenChange={(open) => {
                if (webLinkSubmitting) return;
                setWebLinkDialogOpen(open);
            }}>
                <DialogContent className="max-w-[520px]">
                    <DialogHeader>
                        <DialogTitle>网页链接</DialogTitle>
                    </DialogHeader>
                    <form
                        className="space-y-4"
                        onSubmit={(event) => {
                            event.preventDefault();
                            if (webLinkSubmitting) return;
                            void handleSubmitWebLink();
                        }}
                    >
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
                        <DialogFooter>
                            <Button
                                type="button"
                                variant="outline"
                                onClick={() => setWebLinkDialogOpen(false)}
                                disabled={webLinkSubmitting}
                            >
                                {localize("com_knowledge.cancel")}
                            </Button>
                            <Button type="submit" disabled={webLinkSubmitting}>
                                {webLinkSubmitting ? "导入中..." : "导入"}
                            </Button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>

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
                    spaceLevel={space.spaceLevel}
                    grantSubjectScopeSpaceId={space.id}
                />
            )}

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
                        onOpenChange={setSimilarDialogOpen}
                        spaceId={spaceIdNum}
                        onProcessed={handleVersionAction}
                    />
                </>
            )}
        </div>
    );
}
