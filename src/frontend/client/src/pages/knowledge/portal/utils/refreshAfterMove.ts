import type { PortalFileTreeNode } from "../types";
import { updateTreeNode } from "../utils";

export interface InvalidateTargetFolderCacheResult {
    nodes: PortalFileTreeNode[];
    rootStale: boolean;
}

/**
 * After a file/folder move, invalidate the destination folder's in-memory tree
 * cache so the next breadcrumb navigation refetches children.
 *
 * - Nested target: reuse existing `loaded` flag (set false + clear children).
 * - Root target (null): return rootStale=true; caller must force loadRootTree
 *   on the next navigate-to-root.
 */
export function invalidateTargetFolderCache(
    nodes: PortalFileTreeNode[],
    targetFolderId: string | null,
): InvalidateTargetFolderCacheResult {
    if (targetFolderId == null) {
        return { nodes, rootStale: true };
    }

    return {
        nodes: updateTreeNode(nodes, targetFolderId, (node) => ({
            ...node,
            loaded: false,
            children: [],
            page: 1,
            total: 0,
            hasMore: false,
            nextCursor: null,
        })),
        rootStale: false,
    };
}
