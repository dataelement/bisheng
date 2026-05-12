import { ChevronRight, Folder, FolderOpen } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { KnowledgeFolderNode, listKnowledgeFolders } from "~/api/knowledge";
import { cn } from "~/utils";

// ─── Types ──────────────────────────────────────────────────────────────────

interface TreeNode {
    id: number;
    name: string;
    /** Whether the expand arrow has been clicked at least once (children may be loading). */
    expanded: boolean;
    /** Children array, undefined = not yet fetched; [] = fetched but empty. */
    children?: TreeNode[];
    loading?: boolean;
}

export interface FolderSelectPayload {
    id: string;
    name: string;
}

interface KnowledgeFolderTreeProps {
    knowledgeId: string | number;
    currentFolderId?: string;
    onSelectFolder: (folder: FolderSelectPayload | null) => void;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mapToTree(nodes: KnowledgeFolderNode[]): TreeNode[] {
    return nodes.map((n) => ({
        id: n.id,
        name: n.file_name,
        expanded: false,
        children: undefined,
    }));
}

// ─── Single node row ──────────────────────────────────────────────────────────

interface TreeNodeRowProps {
    node: TreeNode;
    depth: number;
    currentFolderId?: string;
    onExpand: (node: TreeNode) => void;
    onSelect: (node: TreeNode) => void;
}

function TreeNodeRow({ node, depth, currentFolderId, onExpand, onSelect }: TreeNodeRowProps) {
    const isSelected = currentFolderId === String(node.id);
    const hasExpandedChildren = node.expanded && Array.isArray(node.children);

    return (
        <>
            <div
                className={cn(
                    "group flex cursor-pointer select-none items-center gap-1 rounded-md px-2 py-1 text-sm text-[#1d2129] transition-colors hover:bg-[#F2F3F5]",
                    isSelected && "bg-[#E8F3FF] text-[#165DFF] hover:bg-[#E8F3FF]"
                )}
                style={{ paddingLeft: `${8 + depth * 16}px` }}
                onClick={() => onSelect(node)}
            >
                {/* Expand arrow */}
                <button
                    type="button"
                    className={cn(
                        "flex size-4 shrink-0 items-center justify-center rounded transition-transform",
                        node.loading && "animate-pulse"
                    )}
                    onClick={(e) => {
                        e.stopPropagation();
                        onExpand(node);
                    }}
                    aria-label={node.expanded ? "Collapse folder" : "Expand folder"}
                >
                    {node.loading ? (
                        <span className="size-3 rounded-full border-2 border-[#8D93A0] border-t-transparent inline-block animate-spin" />
                    ) : (
                        <ChevronRight
                            className={cn(
                                "size-3 text-[#8D93A0] transition-transform duration-150",
                                node.expanded && "rotate-90"
                            )}
                        />
                    )}
                </button>

                {/* Folder icon */}
                {hasExpandedChildren ? (
                    <FolderOpen className={cn("size-4 shrink-0", isSelected ? "text-[#165DFF]" : "text-[#8D93A0]")} />
                ) : (
                    <Folder className={cn("size-4 shrink-0", isSelected ? "text-[#165DFF]" : "text-[#8D93A0]")} />
                )}

                {/* Folder name */}
                <span className="min-w-0 flex-1 truncate">{node.name}</span>
            </div>

            {/* Recursively render children when expanded */}
            {node.expanded && Array.isArray(node.children) && node.children.length > 0 && (
                <div>
                    {node.children.map((child) => (
                        <TreeNodeRowMemo
                            key={child.id}
                            node={child}
                            depth={depth + 1}
                            currentFolderId={currentFolderId}
                            onExpand={onExpand}
                            onSelect={onSelect}
                        />
                    ))}
                </div>
            )}
        </>
    );
}

// Memoised to avoid full-tree re-renders on every ancestor state change
const TreeNodeRowMemo = TreeNodeRow;

// ─── Root component ──────────────────────────────────────────────────────────

export function KnowledgeFolderTree({ knowledgeId, currentFolderId, onSelectFolder }: KnowledgeFolderTreeProps) {
    const [roots, setRoots] = useState<TreeNode[]>([]);
    const [rootLoading, setRootLoading] = useState(false);

    // Load root folders on mount or when knowledgeId changes
    useEffect(() => {
        if (!knowledgeId) return;
        let cancelled = false;
        setRootLoading(true);
        listKnowledgeFolders({ space_id: knowledgeId, parent_id: null })
            .then(({ items }) => {
                if (cancelled) return;
                setRoots(mapToTree(items));
            })
            .catch(() => {
                if (!cancelled) setRoots([]);
            })
            .finally(() => {
                if (!cancelled) setRootLoading(false);
            });
        return () => { cancelled = true; };
    }, [knowledgeId]);

    /** Immutably update a node anywhere in the tree by id. */
    const updateNode = useCallback((
        nodes: TreeNode[],
        targetId: number,
        updater: (n: TreeNode) => TreeNode
    ): TreeNode[] => {
        return nodes.map((n) => {
            if (n.id === targetId) return updater(n);
            if (Array.isArray(n.children) && n.children.length > 0) {
                return { ...n, children: updateNode(n.children, targetId, updater) };
            }
            return n;
        });
    }, []);

    const handleExpand = useCallback((node: TreeNode) => {
        // Toggle collapse if already expanded
        if (node.expanded) {
            setRoots((prev) => updateNode(prev, node.id, (n) => ({ ...n, expanded: false })));
            return;
        }

        // If children already loaded, just toggle open
        if (Array.isArray(node.children)) {
            setRoots((prev) => updateNode(prev, node.id, (n) => ({ ...n, expanded: true })));
            return;
        }

        // Fetch children
        setRoots((prev) => updateNode(prev, node.id, (n) => ({ ...n, loading: true })));
        listKnowledgeFolders({ space_id: knowledgeId, parent_id: node.id })
            .then(({ items }) => {
                setRoots((prev) =>
                    updateNode(prev, node.id, (n) => ({
                        ...n,
                        expanded: true,
                        loading: false,
                        children: mapToTree(items),
                    }))
                );
            })
            .catch(() => {
                setRoots((prev) =>
                    updateNode(prev, node.id, (n) => ({
                        ...n,
                        expanded: true,
                        loading: false,
                        children: [],
                    }))
                );
            });
    }, [knowledgeId, updateNode]);

    const handleSelect = useCallback((node: TreeNode) => {
        onSelectFolder({ id: String(node.id), name: node.name });
    }, [onSelectFolder]);

    if (rootLoading) {
        return (
            <div className="flex items-center justify-center py-3">
                <span className="size-4 rounded-full border-2 border-[#8D93A0] border-t-transparent inline-block animate-spin" />
            </div>
        );
    }

    if (roots.length === 0) {
        // Empty folder list — render nothing in sidebar context (no banner)
        return null;
    }

    return (
        <div className="flex flex-col gap-0.5">
            {roots.map((node) => (
                <TreeNodeRow
                    key={node.id}
                    node={node}
                    depth={0}
                    currentFolderId={currentFolderId}
                    onExpand={handleExpand}
                    onSelect={handleSelect}
                />
            ))}
        </div>
    );
}
