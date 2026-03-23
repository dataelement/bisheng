import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { getFolderParentPathApi } from "~/api/knowledge";

type PathItem = { id: string; name: string };

/**
 * Hook that fetches parent paths for selected files/folders and computes
 * their longest common ancestor path (LCA).
 *
 * Uses react-query to cache individual folder parent lookups, avoiding
 * redundant requests.
 *
 * @param spaceId   - current knowledge space id
 * @param spaceName - display name of the space (breadcrumb root)
 * @param selectedIds - Set of selected file/folder ids
 * @param files     - current display file list (to resolve names)
 */
export function useSelectionPath(
    spaceId: string,
    spaceName: string,
    selectedIds: Set<string>,
    files: Array<{ id: string; name: string }>
) {
    const selectedArray = useMemo(() => Array.from(selectedIds), [selectedIds]);

    // Fire a cached query for each selected item's parent path
    const queries = useQueries({
        queries: selectedArray.map((id) => ({
            queryKey: ["folderParentPath", spaceId, id] as const,
            queryFn: async () => {
                const parents = await getFolderParentPathApi(spaceId, id);
                // Append the item itself to the end of the path
                const item = files.find((f) => f.id === id);
                const selfNode: PathItem = { id, name: item?.name || id };
                return [...parents, selfNode];
            },
            enabled: !!spaceId && selectedIds.size > 0,
            staleTime: 5 * 60 * 1000, // 5 min cache
            gcTime: 10 * 60 * 1000,
        })),
    });

    const isLoading = queries.some((q) => q.isLoading);

    // Compute longest common ancestor (LCA) path
    const commonPath = useMemo<PathItem[]>(() => {
        const paths = queries
            .filter((q) => q.isSuccess && q.data)
            .map((q) => q.data!);

        if (paths.length === 0) return [];

        if (paths.length === 1) {
            // Single selection: show full path minus the last item (the file itself)
            return paths[0].slice(0, -1);
        }

        // Multiple selections: find longest common prefix by id
        const first = paths[0];
        let commonLen = first.length;

        for (let i = 1; i < paths.length; i++) {
            const other = paths[i];
            let j = 0;
            while (j < commonLen && j < other.length && first[j].id === other[j].id) {
                j++;
            }
            commonLen = j;
        }

        return first.slice(0, commonLen);
    }, [queries]);

    // Prepend space name as root
    const fullPath = useMemo<PathItem[]>(() => {
        if (commonPath.length === 0 && selectedIds.size > 0 && !isLoading) {
            // All at root level — just show space name
            return [{ id: "", name: spaceName }];
        }
        if (commonPath.length > 0) {
            return [{ id: "", name: spaceName }, ...commonPath];
        }
        return [];
    }, [commonPath, selectedIds, isLoading, spaceName]);

    return { commonPath: fullPath, isLoading };
}
