import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import {
    FileStatus,
    KnowledgeFile,
    KnowledgeSpace,
    SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED,
    SpaceRole,
    SortDirection,
    SortType,
    fileStatusToNumber,
    getFolderParentPathApi,
    getSpaceChildrenApi,
    searchSpaceChildrenApi,
} from "~/api/knowledge";
import { approvalRequestToKnowledgeFiles, listApprovalRequestsApi } from "~/api/approval";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { SearchParams } from "../SpaceDetail/CompoundSearchInput";
import { useLocalize } from "~/hooks";
import { isKnowledgeItemPending } from "../knowledgeUtils";

interface UseFileManagerOptions {
    activeSpace: KnowledgeSpace | null;
    /** Optional folder ID from URL deep link — navigate here on initial load */
    initialFolderId?: string;
    /** Disable background loading/polling while the detail file list is not visible. */
    enabled?: boolean;
}

export const KNOWLEDGE_SPACE_FILES_REFRESH_EVENT = "knowledge-space-files:refresh";

export interface KnowledgeSpaceFilesRefreshEventDetail {
    spaceId?: number | string;
}

interface FileListState {
    ownerKey: string | null;
    files: KnowledgeFile[];
    total: number;
}

interface LoadFilesOptions {
    background?: boolean;
}

function buildFilesViewKey({
    enabled,
    activeSpace,
    currentFolderId,
    searchQuery,
    searchTagIds,
    searchScope,
    statusFilter,
    sortBy,
    sortDirection,
}: {
    enabled: boolean;
    activeSpace: KnowledgeSpace | null;
    currentFolderId?: string;
    searchQuery: string;
    searchTagIds: number[];
    searchScope: "current" | "all";
    statusFilter: FileStatus[];
    sortBy?: SortType;
    sortDirection?: SortDirection;
}) {
    if (!enabled || !activeSpace?.id) return null;
    return JSON.stringify({
        spaceId: String(activeSpace.id),
        role: activeSpace.role ?? "",
        spaceKind: activeSpace.spaceKind ?? "",
        folderId: currentFolderId ?? "",
        searchQuery: searchQuery.trim(),
        searchTagIds,
        searchScope,
        statusFilter,
        sortBy: sortBy ?? "",
        sortDirection: sortDirection ?? "",
    });
}

/** Dispatch the global "knowledge space files changed" event (folder create/delete/rename, etc). */
export function dispatchKnowledgeSpaceFilesRefresh(spaceId?: number | string): void {
    window.dispatchEvent(
        new CustomEvent<KnowledgeSpaceFilesRefreshEventDetail>(
            KNOWLEDGE_SPACE_FILES_REFRESH_EVENT,
            { detail: { spaceId } },
        ),
    );
}

/**
 * Manages file list state: loading, pagination, search, sorting, folder navigation.
 * Extracted from the root Knowledge component.
 */
export function useFileManager({ activeSpace, initialFolderId, enabled = true }: UseFileManagerOptions) {
    const localize = useLocalize();
    const [fileListState, setFileListState] = useState<FileListState>({
        ownerKey: null,
        files: [],
        total: 0,
    });
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize] = useState(20);
    const [loading, setLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState("");
    const [searchTagIds, setSearchTagIds] = useState<number[]>([]);
    const [searchScope, setSearchScope] = useState<"current" | "all">("all");
    const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
    const [sortBy, setSortBy] = useState<SortType | undefined>(undefined);
    const [sortDirection, setSortDirection] = useState<SortDirection | undefined>(undefined);
    const [currentFolderId, setCurrentFolderId] = useState<string | undefined>();
    const [currentPath, setCurrentPath] = useState<Array<{ id?: string; name: string }>>([]);

    // Optimistic-deletion ignore set. Held in a ref so loadFiles can read the
    // latest value synchronously without re-rendering. Items in this set are
    // dropped from any list fetched by the server until cleared, preventing
    // the auto-refresh poll from "reviving" a row whose delete API hasn't
    // returned yet (folders with many files can take a long time on the API).
    const pendingDeletionIdsRef = useRef<Set<string>>(new Set());

    const markPendingDeletion = useCallback((ids: Array<string | number>) => {
        ids.forEach(id => pendingDeletionIdsRef.current.add(String(id)));
    }, []);

    const clearPendingDeletion = useCallback((ids: Array<string | number>) => {
        ids.forEach(id => pendingDeletionIdsRef.current.delete(String(id)));
    }, []);

    const { showToast } = useToastContext();
    const activeSpaceIdRef = useRef<string | null>(activeSpace?.id ? String(activeSpace.id) : null);
    const currentPageRef = useRef(currentPage);
    const foregroundSeqRef = useRef(0);
    const foregroundInFlightRef = useRef(0);
    const pathSeqRef = useRef(0);
    const currentViewKey = buildFilesViewKey({
        enabled,
        activeSpace,
        currentFolderId,
        searchQuery,
        searchTagIds,
        searchScope,
        statusFilter,
        sortBy,
        sortDirection,
    });
    const currentViewKeyRef = useRef<string | null>(currentViewKey);
    currentViewKeyRef.current = currentViewKey;
    activeSpaceIdRef.current = activeSpace?.id ? String(activeSpace.id) : null;
    currentPageRef.current = currentPage;

    const hasCurrentFileState = Boolean(currentViewKey && fileListState.ownerKey === currentViewKey);
    const files = hasCurrentFileState ? fileListState.files : [];
    const total = hasCurrentFileState ? fileListState.total : 0;
    const effectiveLoading = loading || Boolean(currentViewKey && !hasCurrentFileState);

    const setFiles = useCallback<Dispatch<SetStateAction<KnowledgeFile[]>>>((value) => {
        setFileListState((prev) => {
            if (!currentViewKey) {
                return { ownerKey: null, files: [], total: 0 };
            }
            const currentFiles = prev.ownerKey === currentViewKey ? prev.files : [];
            const currentTotal = prev.ownerKey === currentViewKey ? prev.total : 0;
            const nextFiles = typeof value === "function"
                ? (value as (prev: KnowledgeFile[]) => KnowledgeFile[])(currentFiles)
                : value;
            return {
                ownerKey: currentViewKey,
                files: nextFiles,
                total: currentTotal,
            };
        });
    }, [currentViewKey]);

    const setTotal = useCallback<Dispatch<SetStateAction<number>>>((value) => {
        setFileListState((prev) => {
            if (!currentViewKey) {
                return { ownerKey: null, files: [], total: 0 };
            }
            const currentFiles = prev.ownerKey === currentViewKey ? prev.files : [];
            const currentTotal = prev.ownerKey === currentViewKey ? prev.total : 0;
            const nextTotal = typeof value === "function"
                ? (value as (prev: number) => number)(currentTotal)
                : value;
            return {
                ownerKey: currentViewKey,
                files: currentFiles,
                total: nextTotal,
            };
        });
    }, [currentViewKey]);

    // ─── Load file/folder list ──────────────────────────────────────────
    const loadFiles = useCallback(
        async (page: number = 1, options: LoadFilesOptions = {}): Promise<KnowledgeFile[]> => {
            if (!enabled || !activeSpace?.id || !currentViewKey) return [];

            const background = options.background === true;
            const requestViewKey = currentViewKey;
            const foregroundSeqAtStart = foregroundSeqRef.current;
            let requestForegroundSeq = foregroundSeqAtStart;
            if (!background) {
                requestForegroundSeq = ++foregroundSeqRef.current;
                foregroundInFlightRef.current += 1;
                setLoading(true);
            }
            try {
                const isSearching = searchQuery.trim().length > 0 || searchTagIds.length > 0;
                const isMember = activeSpace.role === SpaceRole.MEMBER;
                const fileStatusNums = statusFilter.length > 0
                    ? statusFilter.map(fileStatusToNumber)
                    : isMember ? SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED : undefined;
                const res = isSearching
                    ? await searchSpaceChildrenApi({
                        space_id: activeSpace.id,
                        parent_id: searchScope === "all" ? undefined : currentFolderId,
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
                let mergedData = res.data;
                let mergedTotal = res.total;
                if (activeSpace.spaceKind === "department") {
                    try {
                        const approvalRes = await listApprovalRequestsApi({
                            space_id: Number(activeSpace.id),
                            statuses: ["pending_review", "rejected", "sensitive_rejected", "finalize_failed"],
                            page: 1,
                            page_size: 100,
                        });
                        let approvalFiles = approvalRes.data.flatMap((row) =>
                            approvalRequestToKnowledgeFiles(row, activeSpace.id)
                        );
                        if (currentFolderId !== undefined) {
                            approvalFiles = approvalFiles.filter(
                                (file) => file.parentId === currentFolderId
                            );
                        } else {
                            approvalFiles = approvalFiles.filter((file) => !file.parentId);
                        }
                        if (searchQuery.trim()) {
                            const keyword = searchQuery.trim().toLowerCase();
                            approvalFiles = approvalFiles.filter((file) =>
                                file.name.toLowerCase().includes(keyword)
                            );
                        }
                        // Apply the same status filtering logic as the backend API
                        if (statusFilter.length > 0) {
                            approvalFiles = approvalFiles.filter(
                                (file) => file.status !== undefined && statusFilter.includes(file.status)
                            );
                        } else if (isMember) {
                            // Match the default API behavior for members: exclude FAILED
                            approvalFiles = approvalFiles.filter((file) => file.status !== FileStatus.FAILED);
                        }
                        const existingIds = new Set(res.data.map((file) => file.id));
                        const uniqueApprovalFiles = approvalFiles.filter((file) => !existingIds.has(file.id));
                        mergedData = [...uniqueApprovalFiles, ...res.data];
                        mergedTotal = res.total + uniqueApprovalFiles.length;
                    } catch {
                        // Approval list is additive only; degrade gracefully to the
                        // base file list if approval data cannot be loaded.
                    }
                }
                const ignore = pendingDeletionIdsRef.current;
                const visibleData = ignore.size > 0
                    ? mergedData.filter(f => !ignore.has(String(f.id)))
                    : mergedData;
                const ghostCount = mergedData.length - visibleData.length;
                const viewStillCurrent = currentViewKeyRef.current === requestViewKey;
                const canCommitForeground = !background && requestForegroundSeq === foregroundSeqRef.current;
                const canCommitBackground =
                    background &&
                    foregroundInFlightRef.current === 0 &&
                    foregroundSeqAtStart === foregroundSeqRef.current &&
                    currentPageRef.current === page;
                if (!viewStillCurrent || (!canCommitForeground && !canCommitBackground)) {
                    return [];
                }
                setFileListState({
                    ownerKey: requestViewKey,
                    files: visibleData,
                    total: Math.max(0, mergedTotal - ghostCount),
                });
                setCurrentPage(page);
                return visibleData;
            } catch {
                const viewStillCurrent = currentViewKeyRef.current === requestViewKey;
                const shouldNotify = !background && requestForegroundSeq === foregroundSeqRef.current;
                if (!viewStillCurrent || !shouldNotify) {
                    return [];
                }
                setFileListState({
                    ownerKey: requestViewKey,
                    files: [],
                    total: 0,
                });
                showToast({ message: localize("com_knowledge.load_file_list_failed"), severity: NotificationSeverity.ERROR });
                return [];
            } finally {
                if (!background) {
                    foregroundInFlightRef.current = Math.max(0, foregroundInFlightRef.current - 1);
                }
                if (
                    !background &&
                    requestForegroundSeq === foregroundSeqRef.current &&
                    currentViewKeyRef.current === requestViewKey
                ) {
                    setLoading(false);
                }
            }
        },
        [enabled, activeSpace?.id, activeSpace?.role, activeSpace?.spaceKind, currentViewKey, searchQuery, searchTagIds, searchScope, statusFilter, sortBy, sortDirection, currentFolderId, pageSize, showToast, localize]
    );

    // Track which initialFolderId has been consumed (value, not boolean)
    // so re-navigation to a different folder deep link works correctly.
    const consumedFolderIdRef = useRef<string | undefined>(undefined);
    // Bumped on space switch to guarantee the filter effect fires even when
    // search state was already empty (no dep change otherwise).
    const [reloadToken, setReloadToken] = useState(0);

    // Reload files whenever active space or deep-link folder changes
    useEffect(() => {
        foregroundSeqRef.current += 1;
        pathSeqRef.current += 1;
        setFileListState({ ownerKey: null, files: [], total: 0 });
        setCurrentPage(1);
        setLoading(Boolean(enabled && activeSpace?.id));

        if (!enabled || !activeSpace) {
            setCurrentFolderId(undefined);
            setCurrentPath([]);
            setSearchQuery("");
            setSearchTagIds([]);
            setStatusFilter([]);
            setLoading(false);
            return;
        }

        if (enabled && activeSpace) {
            setSearchQuery("");
            setSearchTagIds([]);
            setStatusFilter([]);

            // If there's an unconsumed initial folder from URL, navigate there
            if (initialFolderId && consumedFolderIdRef.current !== initialFolderId) {
                consumedFolderIdRef.current = initialFolderId;
                const requestPathSeq = ++pathSeqRef.current;
                const requestSpaceId = String(activeSpace.id);
                setCurrentFolderId(initialFolderId);
                // Fetch parent chain for breadcrumb path
                getFolderParentPathApi(activeSpace.id, initialFolderId)
                    .then((parentPath) => {
                        // parentPath excludes the folder itself — use last parent's children API
                        // to find the actual folder name. Fallback to the ID string.
                        const lastParentId = parentPath.length > 0
                            ? parentPath[parentPath.length - 1].id
                            : undefined;
                        return getSpaceChildrenApi({
                            space_id: activeSpace.id,
                            parent_id: lastParentId,
                            page: 1,
                            page_size: 100,
                        }).then((res) => {
                            if (
                                requestPathSeq !== pathSeqRef.current ||
                                activeSpaceIdRef.current !== requestSpaceId
                            ) {
                                return;
                            }
                            const folder = res.data.find(f => f.id === initialFolderId);
                            const folderName = folder?.name || initialFolderId;
                            setCurrentPath([...parentPath, { id: initialFolderId, name: folderName }]);
                        });
                    })
                    .catch(() => {
                        if (
                            requestPathSeq !== pathSeqRef.current ||
                            activeSpaceIdRef.current !== requestSpaceId
                        ) {
                            return;
                        }
                        setCurrentPath([{ id: initialFolderId, name: initialFolderId }]);
                    });
                // Don't call loadFiles here — the currentFolderId change watcher effect will trigger it
            } else {
                setCurrentFolderId(undefined);
                setCurrentPath([]);
                // Bump token to trigger the filter effect on the NEXT render
                // (when search state is already cleared), instead of calling
                // loadFiles here with stale closure values.
                setReloadToken(t => t + 1);
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run when space or deep-link folder changes
    }, [enabled, activeSpace?.id, initialFolderId]);

    // Reload files when folder navigation, filters, or space (via reloadToken) change.
    // All state updates from the space effect are batched by React, so when this effect
    // runs on the re-render, searchQuery/searchTagIds are already cleared.
    useEffect(() => {
        if (enabled && activeSpace) {
            setCurrentPage(1);
            loadFiles(1);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- loadFiles is stable via useCallback
    }, [enabled, activeSpace?.role, searchQuery, searchTagIds, searchScope, statusFilter, sortBy, sortDirection, currentFolderId, reloadToken]);

    // ─── Auto-polling for pending files ─────────────────────────────────
    // Refresh the file list every 5s while any file on the current page
    // is still in a processing/waiting/rebuilding/uploading state.
    const loadFilesRef = useRef(loadFiles);
    loadFilesRef.current = loadFiles;

    useEffect(() => {
        if (!enabled || !activeSpace?.id || typeof window === "undefined") return;
        const handleKnowledgeSpaceFilesRefresh = (event: Event) => {
            const detail = (event as CustomEvent<KnowledgeSpaceFilesRefreshEventDetail>).detail;
            if (!detail?.spaceId) return;
            if (String(detail.spaceId) !== String(activeSpace.id)) return;
            loadFilesRef.current(currentPageRef.current, { background: true });
        };
        window.addEventListener(KNOWLEDGE_SPACE_FILES_REFRESH_EVENT, handleKnowledgeSpaceFilesRefresh);
        return () => {
            window.removeEventListener(KNOWLEDGE_SPACE_FILES_REFRESH_EVENT, handleKnowledgeSpaceFilesRefresh);
        };
    }, [enabled, activeSpace?.id]);

    useEffect(() => {
        if (!enabled) return;
        const hasPending = files.some(
            (f) => isKnowledgeItemPending(f)
        );
        if (!hasPending) return;

        const timer = setInterval(() => {
            loadFilesRef.current(currentPageRef.current, { background: true });
        }, 5000);

        return () => clearInterval(timer);
    }, [enabled, files]);

    // ─── Search handler ─────────────────────────────────────────────────
    const handleSearch = useCallback((params: SearchParams) => {
        setSearchQuery(params.keyword);
        setSearchTagIds(params.tagIds);
        setSearchScope(params.scope);
    }, []);

    // ─── Sort handler ───────────────────────────────────────────────────
    const handleSort = useCallback((newSortBy: SortType, newDirection: SortDirection) => {
        setSortBy(newSortBy);
        setSortDirection(newDirection);
    }, []);

    // ─── Pagination ─────────────────────────────────────────────────────
    const handlePageChange = useCallback(
        (page: number) => {
            loadFiles(page);
        },
        [loadFiles]
    );

    // ─── Folder navigation ───────────────────────────────────────────────
    const handleNavigateFolder = useCallback(
        async (folderId?: string) => {
            const requestPathSeq = ++pathSeqRef.current;
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
            const requestSpaceId = String(activeSpace.id);
            const folder = files.find(f => f.id === folderId);
            const currentFolder = { id: folderId, name: folder?.name || folderId };
            try {
                const parentPath = await getFolderParentPathApi(activeSpace.id, folderId);
                if (
                    requestPathSeq !== pathSeqRef.current ||
                    activeSpaceIdRef.current !== requestSpaceId
                ) {
                    return;
                }
                setCurrentPath([...parentPath, currentFolder]);
            } catch {
                if (
                    requestPathSeq !== pathSeqRef.current ||
                    activeSpaceIdRef.current !== requestSpaceId
                ) {
                    return;
                }
                // Fallback: append folder to current path
                setCurrentPath(prev => [...prev, currentFolder]);
            }
        },
        [activeSpace, currentPath, files]
    );

    return {
        files,
        setFiles,
        currentPage,
        pageSize,
        total,
        setTotal,
        loading: effectiveLoading,
        searchQuery,
        searchTagIds,
        searchScope,
        statusFilter,
        setStatusFilter,
        sortBy,
        sortDirection,
        currentFolderId,
        currentPath,
        loadFiles,
        handleSearch,
        handleSort,
        handlePageChange,
        handleNavigateFolder,
        markPendingDeletion,
        clearPendingDeletion,
    };
}
