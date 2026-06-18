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
    // F027: cursor-based pagination for the non-search path. `nextCursor`
    // holds the token to fetch the next page; null/undefined means "no
    // further pages" (or first page). The search path keeps the legacy
    // offset+total contract because /space/{id}/search is out of F027 scope.
    const [nextCursor, setNextCursor] = useState<string | null>(null);
    const [hasMore, setHasMore] = useState(false);
    // F027 §AC-17-client-补做: track which search page has been fetched so
    // append-mode LoadMore can ask the next one. 0 = haven't fetched yet.
    const [nextSearchPage, setNextSearchPage] = useState(0);
    // Latest files snapshot for use inside polling callbacks (avoids stale closures).
    const filesRef = useRef<KnowledgeFile[]>([]);
    filesRef.current = files;
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

    // Serialises concurrent loadFiles calls: each call bumps this counter and
    // remembers its own id; when the response returns, it only applies state
    // if it's still the latest request. Fixes status-filter race where rapid
    // clicks let a stale response overwrite a newer one (mangled list state).
    const loadRequestIdRef = useRef(0);

    const markPendingDeletion = useCallback((ids: Array<string | number>) => {
        ids.forEach(id => pendingDeletionIdsRef.current.add(String(id)));
    }, []);

    const clearPendingDeletion = useCallback((ids: Array<string | number>) => {
        ids.forEach(id => pendingDeletionIdsRef.current.delete(String(id)));
    }, []);

    const { showToast } = useToastContext();

    // ─── Load file/folder list ──────────────────────────────────────────
    // F027 §AC-17-client-补做: page=1 replaces files (fresh load); page>1
    // appends to existing files for infinite scroll. The default path uses
    // `nextCursor` keyset; the search path keeps backend page-numbering and
    // we maintain `nextSearchPage` internally to stitch successive batches.
    const loadFiles = useCallback(
        async (page: number = 1): Promise<KnowledgeFile[]> => {
            if (!enabled || !activeSpace?.id) return [];

            const reqId = ++loadRequestIdRef.current;
            setLoading(true);
            try {
                const isSearching = searchQuery.trim().length > 0 || searchTagIds.length > 0;
                const isAppending = page > 1;
                const isMember = activeSpace.role === SpaceRole.MEMBER;
                const fileStatusNums = statusFilter.length > 0
                    ? statusFilter.map(fileStatusToNumber)
                    : isMember ? SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED : undefined;

                // Search path: backend still page-numbered; compute next page.
                const searchPageToFetch = isSearching
                    ? (isAppending ? nextSearchPage + 1 : 1)
                    : 1;

                const res = isSearching
                    ? await searchSpaceChildrenApi({
                        space_id: activeSpace.id,
                        parent_id: searchScope === "all" ? undefined : currentFolderId,
                        page: searchPageToFetch,
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
                        // Default path: cursor=null fetches first page; on
                        // append we send the previously returned next_cursor.
                        cursor: isAppending ? nextCursor : null,
                        page_size: pageSize,
                        order_field: sortBy || undefined,
                        order_sort: sortDirection || undefined,
                        file_status: fileStatusNums,
                    });

                // Stale-response guard: a newer loadFiles started while this
                // one was in flight (e.g. user clicked a different status
                // filter). Drop this result entirely — don't touch any state.
                if (reqId !== loadRequestIdRef.current) return [];

                const incomingData = res.data;

                // Update pagination tokens per envelope shape.
                if (isSearching) {
                    const totalCount = (res as any).total ?? 0;
                    const fetchedSoFar = searchPageToFetch * pageSize;
                    setHasMore(fetchedSoFar < totalCount);
                    setNextSearchPage(searchPageToFetch);
                } else {
                    setNextCursor((res as any).next_cursor ?? null);
                    setHasMore(!!(res as any).has_more);
                    if (!isAppending) setNextSearchPage(0); // reset on fresh default-path load
                }

                // Filter out rows that the user has optimistically deleted but
                // whose backend deletion has not yet returned (ghosts).
                const ignore = pendingDeletionIdsRef.current;
                const filteredData = ignore.size > 0
                    ? incomingData.filter(f => !ignore.has(String(f.id)))
                    : incomingData;

                // Append (LoadMore) vs replace (fresh load).
                if (isAppending) {
                    setFiles(prev => [...prev, ...filteredData]);
                } else {
                    setFiles(filteredData);
                }
                setCurrentPage(page);
                return filteredData;
            } catch {
                if (reqId === loadRequestIdRef.current) {
                    showToast({ message: localize("com_knowledge.load_file_list_failed"), severity: NotificationSeverity.ERROR });
                }
                return [];
            } finally {
                // Only the latest request clears the loading flag, otherwise a
                // stale response would hide the spinner of the in-flight one.
                if (reqId === loadRequestIdRef.current) setLoading(false);
            }
        },
        [enabled, activeSpace?.id, activeSpace?.role, searchQuery, searchTagIds, searchScope, statusFilter, sortBy, sortDirection, currentFolderId, pageSize, nextCursor, nextSearchPage, showToast, localize]
    );

    // Derive total from accumulated files + has_more for UI progress badges.
    // Replaces the old per-batch setTotal in loadFiles; setTotal is still
    // exposed for optimistic deletion adjustments by callers.
    useEffect(() => {
        setTotal(files.length + (hasMore ? 1 : 0));
    }, [files.length, hasMore]);

    // Bumped on space switch to guarantee the filter effect fires even when
    // search state was already empty (no dep change otherwise).
    const [reloadToken, setReloadToken] = useState(0);

    // Reload files whenever active space or deep-link folder changes
    useEffect(() => {
        if (enabled && activeSpace) {
            setCurrentPage(1);
            setSearchQuery("");
            setSearchTagIds([]);
            setStatusFilter([]);

            // The URL folder id is the single source of truth — sync the content
            // pane to it on every change. A previous "consumed" guard skipped
            // re-entering an already-visited folder (its id was still marked
            // consumed), which left the URL on /folder/<id> while the pane reset
            // to the space root — folders became un-enterable from the sidebar tree.
            if (initialFolderId) {
                setCurrentFolderId(initialFolderId);
                // Fetch the breadcrumb path for the URL folder. The API now
                // includes the folder itself as the leaf (with its real name),
                // so we use it directly — no extra children lookup, and no
                // intermittent fall-back to the raw id.
                getFolderParentPathApi(activeSpace.id, initialFolderId)
                    .then((parentPath) => {
                        setCurrentPath(parentPath);
                    })
                    .catch(() => {
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
    // F027 §AC-17-client-补做: in infinite-scroll mode we cannot re-fetch
    // "the current page" — that concept is gone. Instead the 5s poll now
    // refreshes only the status/progress fields of already-loaded rows
    // without touching the cursor chain. Rows newly returned by the API
    // that we haven't seen (e.g. just-uploaded) get prepended to the head.
    // Skipped during search state (search results are a frozen snapshot).
    const loadFilesRef = useRef(loadFiles);
    loadFilesRef.current = loadFiles;

    const refreshLoadedStatuses = useCallback(async () => {
        if (!enabled || !activeSpace?.id) return;
        const isSearching = searchQuery.trim().length > 0 || searchTagIds.length > 0;
        if (isSearching) return;
        const currentFiles = filesRef.current;
        if (currentFiles.length === 0) return;

        try {
            const isMember = activeSpace.role === SpaceRole.MEMBER;
            const fileStatusNums = statusFilter.length > 0
                ? statusFilter.map(fileStatusToNumber)
                : isMember ? SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED : undefined;
            // Cap the poll fetch at 100 to bound the request — pending files
            // (recent update_time) sit at the top under default sort anyway.
            const fetchSize = Math.min(currentFiles.length, 100);
            const res = await getSpaceChildrenApi({
                space_id: activeSpace.id,
                parent_id: currentFolderId,
                cursor: null,
                page_size: fetchSize,
                order_field: sortBy || undefined,
                order_sort: sortDirection || undefined,
                file_status: fileStatusNums,
            });

            const updatesById = new Map<string, KnowledgeFile>();
            res.data.forEach(f => updatesById.set(String(f.id), f));

            setFiles(prev => {
                const knownIds = new Set(prev.map(f => String(f.id)));
                // Replace matched rows wholesale — the API returns the full
                // refreshed row; nextCursor / accumulated tail untouched.
                const merged = prev.map(f => updatesById.get(String(f.id)) ?? f);
                // Prepend rows we haven't seen (likely user-uploaded since
                // last load). Filter pending-deletion ghosts here too.
                const ignore = pendingDeletionIdsRef.current;
                const newRows = res.data.filter(f =>
                    !knownIds.has(String(f.id)) && !ignore.has(String(f.id))
                );
                return newRows.length > 0 ? [...newRows, ...merged] : merged;
            });
        } catch {
            // Silent — polling failure must not toast.
        }
    }, [enabled, activeSpace?.id, activeSpace?.role, searchQuery, searchTagIds, statusFilter, sortBy, sortDirection, currentFolderId]);

    const refreshLoadedStatusesRef = useRef(refreshLoadedStatuses);
    refreshLoadedStatusesRef.current = refreshLoadedStatuses;

    useEffect(() => {
        if (!enabled || !activeSpace?.id || typeof window === "undefined") return;
        const handleKnowledgeSpaceFilesRefresh = (event: Event) => {
            const detail = (event as CustomEvent<KnowledgeSpaceFilesRefreshEventDetail>).detail;
            if (!detail?.spaceId) return;
            if (String(detail.spaceId) !== String(activeSpace.id)) return;
            // Structural change (folder create/delete/rename) — reset to first
            // page; the accumulated tail is no longer trustworthy.
            loadFilesRef.current(1);
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
            refreshLoadedStatusesRef.current();
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

    // Infinite-scroll "load next page": page>1 makes loadFiles append (keyset
    // cursor on the default path, page-number on the search path). The scroll
    // sentinel guards re-entry with `loading`/`hasMore`, so no guard needed here.
    const loadMore = useCallback(() => {
        loadFiles(currentPage + 1);
    }, [loadFiles, currentPage]);

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

            // Fetch the full breadcrumb path from API. It now includes the
            // target folder itself as the leaf (with its authoritative name),
            // so we use it directly instead of guessing the leaf name from the
            // local file list (which is often stale right after navigating in
            // from the sidebar tree, and used to fall back to the raw id).
            try {
                const parentPath = await getFolderParentPathApi(activeSpace.id, folderId);
                setCurrentPath(parentPath);
            } catch {
                // API failed: best-effort leaf from the local list, else the id.
                const folder = files.find(f => f.id === folderId);
                setCurrentPath(prev => [...prev, { id: folderId, name: folder?.name || folderId }]);
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
        // F027: cursor-based progress hints — the SpaceDetail page consumes
        // `hasMore` to decide whether to render the infinite-scroll loader.
        nextCursor,
        hasMore,
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
        handleSearch,
        handleSort,
        handlePageChange,
        handleNavigateFolder,
        markPendingDeletion,
        clearPendingDeletion,
    };
}
