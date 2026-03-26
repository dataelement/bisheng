import { useCallback, useEffect, useState } from "react";
import {
    FileStatus,
    KnowledgeFile,
    KnowledgeSpace,
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

interface UseFileManagerOptions {
    activeSpace: KnowledgeSpace | null;
}

/**
 * Manages file list state: loading, pagination, search, sorting, folder navigation.
 * Extracted from the root Knowledge component.
 */
export function useFileManager({ activeSpace }: UseFileManagerOptions) {
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
        async (page: number = 1) => {
            if (!activeSpace?.id) return;

            setLoading(true);
            try {
                const isSearching = searchQuery.trim().length > 0 || searchTagIds.length > 0;
                const fileStatusNums = statusFilter.length > 0
                    ? statusFilter.map(fileStatusToNumber)
                    : undefined;
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
            } catch {
                showToast({ message: localize("com_knowledge.load_file_list_failed"), severity: NotificationSeverity.ERROR });
            } finally {
                setLoading(false);
            }
        },
        [activeSpace?.id, searchQuery, searchTagIds, searchScope, statusFilter, sortBy, sortDirection, currentFolderId, pageSize, showToast]
    );

    // Reload files whenever active space changes
    useEffect(() => {
        if (activeSpace) {
            setCurrentPage(1);
            setCurrentFolderId(undefined);
            setCurrentPath([]);
            setSearchQuery("");
            setStatusFilter([]);
            loadFiles(1);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-run when space id changes
    }, [activeSpace?.id]);

    // Reload files when folder navigation or filters change
    useEffect(() => {
        if (activeSpace) {
            setCurrentPage(1);
            loadFiles(1);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- loadFiles is stable via useCallback
    }, [searchQuery, searchTagIds, searchScope, statusFilter, sortBy, sortDirection, currentFolderId]);

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
