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

/** Statuses that indicate a file is still being processed */
const PENDING_STATUSES: FileStatus[] = [
    FileStatus.PROCESSING,
    FileStatus.WAITING,
    FileStatus.REBUILDING,
    FileStatus.UPLOADING,
];

interface UseFileManagerOptions {
    activeSpace: KnowledgeSpace | null;
    /** Optional folder ID from URL deep link — navigate here on initial load */
    initialFolderId?: string;
}

/**
 * Manages file list state: loading, pagination, search, sorting, folder navigation.
 * Extracted from the root Knowledge component.
 */
export function useFileManager({ activeSpace, initialFolderId }: UseFileManagerOptions) {
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

    // ─── Load file/folder list ──────────────────────────────────────────
    const loadFiles = useCallback(
        async (page: number = 1): Promise<KnowledgeFile[]> => {
            if (!activeSpace?.id) return [];

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
                setFiles(res.data);
                setTotal(res.total);
                setCurrentPage(page);
                return res.data;
            } catch {
                showToast({ message: localize("com_knowledge.load_file_list_failed"), severity: NotificationSeverity.ERROR });
                return [];
            } finally {
                setLoading(false);
            }
        },
        [activeSpace?.id, activeSpace?.role, searchQuery, searchTagIds, searchScope, statusFilter, sortBy, sortDirection, currentFolderId, pageSize, showToast]
    );

    // Track which initialFolderId has been consumed (value, not boolean)
    // so re-navigation to a different folder deep link works correctly.
    const consumedFolderIdRef = useRef<string | undefined>(undefined);
    // Bumped on space switch to guarantee the filter effect fires even when
    // search state was already empty (no dep change otherwise).
    const [reloadToken, setReloadToken] = useState(0);

    // Reload files whenever active space or deep-link folder changes
    useEffect(() => {
        if (activeSpace) {
            setCurrentPage(1);
            setSearchQuery("");
            setSearchTagIds([]);
            setStatusFilter([]);

            // If there's an unconsumed initial folder from URL, navigate there
            if (initialFolderId && consumedFolderIdRef.current !== initialFolderId) {
                consumedFolderIdRef.current = initialFolderId;
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
                            const folder = res.data.find(f => f.id === initialFolderId);
                            const folderName = folder?.name || initialFolderId;
                            setCurrentPath([...parentPath, { id: initialFolderId, name: folderName }]);
                        });
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
    }, [activeSpace?.id, initialFolderId]);

    // Reload files when folder navigation, filters, or space (via reloadToken) change.
    // All state updates from the space effect are batched by React, so when this effect
    // runs on the re-render, searchQuery/searchTagIds are already cleared.
    useEffect(() => {
        if (activeSpace) {
            setCurrentPage(1);
            loadFiles(1);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- loadFiles is stable via useCallback
    }, [activeSpace?.role, searchQuery, searchTagIds, searchScope, statusFilter, sortBy, sortDirection, currentFolderId, reloadToken]);

    // ─── Auto-polling for pending files ─────────────────────────────────
    // Refresh the file list every 5s while any file on the current page
    // is still in a processing/waiting/rebuilding/uploading state.
    const loadFilesRef = useRef(loadFiles);
    loadFilesRef.current = loadFiles;
    const currentPageRef = useRef(currentPage);
    currentPageRef.current = currentPage;

    useEffect(() => {
        const hasPending = files.some(
            (f) => f.status && PENDING_STATUSES.includes(f.status)
        );
        if (!hasPending) return;

        const timer = setInterval(() => {
            loadFilesRef.current(currentPageRef.current);
        }, 5000);

        return () => clearInterval(timer);
    }, [files]);

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
        handleSearch,
        handleSort,
        handlePageChange,
        handleNavigateFolder,
    };
}
