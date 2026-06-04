import { useCallback, useEffect, useRef, useState } from "react";
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
    const [files, setFiles] = useState<KnowledgeFile[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize] = useState(20);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState("");
    const [searchTagIds, setSearchTagIds] = useState<number[]>([]);
    const [searchScope, setSearchScope] = useState<"current" | "all">("all");
    const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
    const [sortBy, setSortBy] = useState<SortType | undefined>(undefined);
    const [sortDirection, setSortDirection] = useState<SortDirection | undefined>(undefined);
    const [currentFolderId, setCurrentFolderId] = useState<string | undefined>();
    const [currentPath, setCurrentPath] = useState<Array<{ id?: string; name: string }>>([]);

    const { showToast } = useToastContext();

    // Guards against overlapping infinite-scroll triggers (setLoading is async).
    const loadingRef = useRef(false);

    // ─── Core list fetch ────────────────────────────────────────────────
    // `append` accumulates onto the existing list (infinite scroll); otherwise
    // it replaces. `size` lets callers fetch several pages worth in one request
    // (used when refreshing all already-loaded pages).
    const fetchList = useCallback(
        async (page: number, size: number, append: boolean): Promise<KnowledgeFile[]> => {
            if (!enabled || !activeSpace?.id) return [];

            loadingRef.current = true;
            setLoading(true);
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
                        page_size: size,
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
                        page_size: size,
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
                if (append) {
                    setFiles(prev => {
                        const seen = new Set(prev.map(f => String(f.id)));
                        return [...prev, ...mergedData.filter(f => !seen.has(String(f.id)))];
                    });
                } else {
                    setFiles(mergedData);
                }
                setTotal(mergedTotal);
                return mergedData;
            } catch {
                showToast({ message: localize("com_knowledge.load_file_list_failed"), severity: NotificationSeverity.ERROR });
                return [];
            } finally {
                loadingRef.current = false;
                setLoading(false);
            }
        },
        [enabled, activeSpace?.id, activeSpace?.role, searchQuery, searchTagIds, searchScope, statusFilter, sortBy, sortDirection, currentFolderId, showToast]
    );

    // Load a single page fresh (replaces the list). Used by all reset effects.
    const loadFiles = useCallback(
        async (page: number = 1): Promise<KnowledgeFile[]> => {
            const data = await fetchList(page, pageSize, false);
            setCurrentPage(page);
            return data;
        },
        [fetchList, pageSize]
    );

    const hasMore = files.length < total;

    // Infinite scroll: append the next page.
    const loadMore = useCallback(async () => {
        if (loadingRef.current) return;
        if (files.length >= total) return;
        const next = currentPage + 1;
        await fetchList(next, pageSize, true);
        setCurrentPage(next);
    }, [fetchList, pageSize, files.length, total, currentPage]);

    // Refresh every already-loaded page in one request (keeps the accumulated
    // list intact while updating statuses). Used by polling and refresh events.
    const refreshLoaded = useCallback(async () => {
        const pages = Math.max(1, currentPage);
        await fetchList(1, pageSize * pages, false);
    }, [fetchList, pageSize, currentPage]);

    // Track which initialFolderId has been consumed (value, not boolean)
    // so re-navigation to a different folder deep link works correctly.
    const consumedFolderIdRef = useRef<string | undefined>(undefined);
    // Bumped on space switch to guarantee the filter effect fires even when
    // search state was already empty (no dep change otherwise).
    const [reloadToken, setReloadToken] = useState(0);

    // Reload files whenever active space or deep-link folder changes
    useEffect(() => {
        // Stale-guard: when the space changes mid-flight, the previous run's async breadcrumb
        // resolution must not overwrite currentPath (e.g. a getFolderParentPathApi call made
        // under the OLD space fails for a folder of the NEW space and would clobber the title).
        let cancelled = false;
        if (enabled && activeSpace) {
            setCurrentPage(1);
            setSearchQuery("");
            setSearchTagIds([]);
            setStatusFilter([]);
            // Clear the previous space's data immediately so the right pane doesn't keep
            // displaying stale files (with the new space's name/header) while the next
            // list-API call is in flight. Combined with the `loading && files.length === 0`
            // branch in SpaceDetail, this surfaces a loading spinner during the switch.
            setFiles([]);
            setTotal(0);
            setLoading(true);

            // Key the "consumed" guard by space+folder. When deep-linking to a folder of a
            // DIFFERENT space, the URL folder id updates one render before activeSpace catches
            // up, so the folder would get consumed under the OLD space and then skipped (→ root)
            // once the new space arrives. A composite key re-consumes it for the new space.
            if (initialFolderId && consumedFolderIdRef.current !== `${activeSpace.id}::${initialFolderId}`) {
                consumedFolderIdRef.current = `${activeSpace.id}::${initialFolderId}`;
                setCurrentFolderId(initialFolderId);
                // Fetch parent chain for breadcrumb path
                getFolderParentPathApi(activeSpace.id, initialFolderId)
                    .then((parentPath) => {
                        // If the parent-path API already includes the target folder as the last
                        // item (it carries the folder's name), use it directly — searching its
                        // own children for itself would fail and fall back to the raw ID.
                        if (cancelled) return;
                        const last = parentPath[parentPath.length - 1];
                        if (last && String(last.id) === String(initialFolderId)) {
                            setCurrentPath(parentPath);
                            return;
                        }
                        // Otherwise the API returns only ancestors — resolve the folder's name
                        // from its parent's children. Fallback to the ID string.
                        const lastParentId = last?.id;
                        return getSpaceChildrenApi({
                            space_id: activeSpace.id,
                            parent_id: lastParentId,
                            page: 1,
                            page_size: 100,
                        }).then((res) => {
                            if (cancelled) return;
                            const folder = res.data.find(f => String(f.id) === String(initialFolderId));
                            const folderName = folder?.name || initialFolderId;
                            setCurrentPath([...parentPath, { id: initialFolderId, name: folderName }]);
                        });
                    })
                    .catch(() => {
                        if (cancelled) return;
                        setCurrentPath([{ id: initialFolderId, name: initialFolderId }]);
                    });
                // Don't call loadFiles here — the currentFolderId change watcher effect will trigger it
            } else {
                // Reset the guard so re-entering the same folder later re-consumes it.
                consumedFolderIdRef.current = undefined;
                setCurrentFolderId(undefined);
                setCurrentPath([]);
                // Bump token to trigger the filter effect on the NEXT render
                // (when search state is already cleared), instead of calling
                // loadFiles here with stale closure values.
                setReloadToken(t => t + 1);
            }
        }
        return () => { cancelled = true; };
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
    const refreshLoadedRef = useRef(refreshLoaded);
    refreshLoadedRef.current = refreshLoaded;

    useEffect(() => {
        if (!enabled || !activeSpace?.id || typeof window === "undefined") return;
        const handleKnowledgeSpaceFilesRefresh = (event: Event) => {
            const detail = (event as CustomEvent<KnowledgeSpaceFilesRefreshEventDetail>).detail;
            if (!detail?.spaceId) return;
            if (String(detail.spaceId) !== String(activeSpace.id)) return;
            refreshLoadedRef.current();
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
            refreshLoadedRef.current();
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
        loading,
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
        loadMore,
        hasMore,
        handleSearch,
        handleSort,
        handlePageChange,
        handleNavigateFolder,
    };
}
