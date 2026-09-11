import { Outlined } from "bisheng-icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { KnowledgeFolderNode, listKnowledgeFolders, getFolderParentPathApi } from "~/api/knowledge";
import { cn } from "~/utils";
import {
    KNOWLEDGE_SPACE_FILES_REFRESH_EVENT,
    type KnowledgeSpaceFilesRefreshEventDetail,
} from "../hooks/useFileManager";
import { DynamicEllipsisName } from "./DynamicEllipsisName";

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
    /**
     * Status filter — must mirror what the right-side file panel sends so the
     * tree and the panel show the same folders. For MEMBER-role users this is
     * SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED; omit for admins/creators.
     * Pass a stable reference (module constant or undefined) to avoid refetch churn.
     */
    fileStatus?: number[];
    onSelectFolder: (folder: FolderSelectPayload | null) => void;
    /** Compact dropdown styling: 14px folder icons + slightly looser node spacing. */
    compact?: boolean;
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

/** Collect ids of all currently-expanded nodes anywhere in the tree. */
function collectExpandedIds(nodes: TreeNode[], acc: Set<number>): Set<number> {
    for (const n of nodes) {
        if (n.expanded) acc.add(n.id);
        if (Array.isArray(n.children)) collectExpandedIds(n.children, acc);
    }
    return acc;
}

/** Find a node anywhere in the tree by id, searching into loaded (but possibly
 *  collapsed) children too — a node's `children` array persists after collapse. */
function findNode(nodes: TreeNode[], id: number): TreeNode | undefined {
    for (const n of nodes) {
        if (n.id === id) return n;
        if (Array.isArray(n.children)) {
            const found = findNode(n.children, id);
            if (found) return found;
        }
    }
    return undefined;
}

// ─── Single node row ──────────────────────────────────────────────────────────

interface TreeNodeRowProps {
    node: TreeNode;
    depth: number;
    currentFolderId?: string;
    onExpand: (node: TreeNode) => void;
    onSelect: (node: TreeNode) => void;
    compact?: boolean;
}

function TreeNodeRow({ node, depth, currentFolderId, onExpand, onSelect, compact = false }: TreeNodeRowProps) {
    const isSelected = currentFolderId === String(node.id);
    const hasExpandedChildren = node.expanded && Array.isArray(node.children);

    return (
        <>
            <div
                className={cn(
                    // Row height: 28px on desktop; 32px (compact) on the mobile switcher.
                    // pr-1 matches design's 4px right padding; left padding comes from per-depth
                    // inline style so each nested level indents 20px (one 20×20 switcher slot).
                    "group flex cursor-pointer select-none items-center rounded-md pr-1 text-[12px] leading-5 text-[#1d2129] transition-colors hover:bg-[#F4F4F4]",
                    compact ? "h-8" : "h-7",
                    // Per design: selected folder = gray bg + semibold (600) title + dark folder icon.
                    isSelected && "bg-[#EEEEEE] font-semibold hover:bg-[#EEEEEE]"
                )}
                style={{ paddingLeft: `${(depth + 1) * 20}px` }}
                onClick={() => onSelect(node)}
            >
                {/* Switcher slot: 20×20 wrapper, 16×16 chevron inside */}
                <button
                    type="button"
                    className={cn(
                        "flex size-5 shrink-0 items-center justify-center rounded",
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
                        <Outlined.Right
                            className={cn(
                                "size-4 text-[#8D93A0] transition-transform duration-150",
                                node.expanded && "rotate-90"
                            )}
                        />
                    )}
                </button>

                {/* Icon wrapper: 20×20 wrapper, 16×16 folder icon inside.
                    Per design: selected folder icon is dark (#1d2129); unselected is light gray. */}
                <div className="flex size-5 shrink-0 items-center justify-center">
                    {hasExpandedChildren ? (
                        <Outlined.FolderOpen className={cn(compact ? "size-3.5 shrink-0" : "size-4 shrink-0", isSelected ? "text-[#1d2129]" : "text-[#8D93A0]")} />
                    ) : (
                        <Outlined.FolderClose className={cn(compact ? "size-3.5 shrink-0" : "size-4 shrink-0", isSelected ? "text-[#1d2129]" : "text-[#8D93A0]")} />
                    )}
                </div>

                {/* Folder name — an invisible natural-width spacer keeps the row as wide
                    as the full name (so the outer w-max wrapper aligns all rows to the
                    widest and the container can scroll), while the visible overlay
                    truncates with a scroll-following ellipsis (see useDynamicEllipsis). */}
                <DynamicEllipsisName name={node.name} />
            </div>

            {/* Recursively render children when expanded.
                flex-col + gap-0.5 keeps the 2px gap between siblings at every nested level.
                Don't add pt-0.5 here — the parent container's gap-0.5 already provides
                the 2px gap between the row and this children wrapper. */}
            {node.expanded && Array.isArray(node.children) && node.children.length > 0 && (
                <div className="flex flex-col gap-0.5">
                    {node.children.map((child) => (
                        <TreeNodeRow
                            key={child.id}
                            node={child}
                            depth={depth + 1}
                            currentFolderId={currentFolderId}
                            onExpand={onExpand}
                            onSelect={onSelect}
                            compact={compact}
                        />
                    ))}
                </div>
            )}
        </>
    );
}

// ─── Root component ──────────────────────────────────────────────────────────

export function KnowledgeFolderTree({
    knowledgeId,
    currentFolderId,
    fileStatus,
    onSelectFolder,
    compact = false,
}: KnowledgeFolderTreeProps) {
    const [roots, setRoots] = useState<TreeNode[]>([]);
    const [rootLoading, setRootLoading] = useState(false);
    // True once the root list for the current (knowledgeId, fileStatus) has
    // finished loading. Gates the deep-link effect below — unlike rootLoading
    // (whose initial `false` would let that effect run against an empty tree
    // on mount), this only flips true after real data is in.
    const [rootsReady, setRootsReady] = useState(false);

    // Mirror the latest tree into a ref so refreshTree can read it without
    // becoming a new function on every state change.
    const rootsRef = useRef<TreeNode[]>([]);
    useEffect(() => {
        rootsRef.current = roots;
    }, [roots]);

    // Load root folders on mount or when knowledgeId / fileStatus changes.
    // Deliberately independent of currentFolderId: selecting a folder (click or
    // route change) must never rebuild the tree. The deep-link effect below
    // handles the one case where the selected folder isn't in the tree yet.
    useEffect(() => {
        if (!knowledgeId) return;
        let cancelled = false;
        setRootLoading(true);
        setRootsReady(false);
        (async () => {
            try {
                const { items } = await listKnowledgeFolders({
                    space_id: knowledgeId, parent_id: null, file_status: fileStatus,
                });
                if (!cancelled) setRoots(mapToTree(items));
            } catch {
                if (!cancelled) setRoots([]);
            } finally {
                if (!cancelled) {
                    setRootLoading(false);
                    setRootsReady(true);
                }
            }
        })();
        return () => { cancelled = true; };
    }, [knowledgeId, fileStatus]);

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

    /**
     * Expand a node without ever collapsing it. If its children were loaded
     * before (even while collapsed) this is a pure state toggle — no request;
     * only a never-loaded node fetches its own children (one level, same as
     * the expand arrow). Shared by the arrow and by folder-row clicks.
     */
    const ensureExpanded = useCallback((node: TreeNode) => {
        if (node.expanded) return;

        // If children already loaded, just toggle open
        if (Array.isArray(node.children)) {
            setRoots((prev) => updateNode(prev, node.id, (n) => ({ ...n, expanded: true })));
            return;
        }

        // Fetch children
        setRoots((prev) => updateNode(prev, node.id, (n) => ({ ...n, loading: true })));
        listKnowledgeFolders({ space_id: knowledgeId, parent_id: node.id, file_status: fileStatus })
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
    }, [knowledgeId, fileStatus, updateNode]);

    const handleExpand = useCallback((node: TreeNode) => {
        // Arrow keeps toggle semantics: collapse if already expanded.
        if (node.expanded) {
            setRoots((prev) => updateNode(prev, node.id, (n) => ({ ...n, expanded: false })));
            return;
        }
        ensureExpanded(node);
    }, [ensureExpanded, updateNode]);

    // Clicking a folder row only selects it (route + highlight) — it never
    // expands/collapses children; that is exclusively the arrow's job. No tree
    // reload either: the row is already rendered, so its data is already local,
    // and the highlight follows the currentFolderId prop on re-render.
    const handleSelect = useCallback((node: TreeNode) => {
        onSelectFolder({ id: String(node.id), name: node.name });
    }, [onSelectFolder]);

    // Deep-link catch-up: when currentFolderId points at a folder that is NOT in
    // the local tree (direct URL visit, breadcrumb jump into a never-expanded
    // branch), fetch its ancestor chain and expand just the missing levels.
    // Folder-row clicks never enter here — a clickable row is already in the tree,
    // so findNode succeeds and this effect exits with zero requests.
    const handledDeepLinkRef = useRef<string | null>(null);
    useEffect(() => {
        // Wait for the root list to be genuinely loaded — rootLoading's initial
        // `false` on mount would otherwise let this run against an empty tree.
        if (!knowledgeId || !currentFolderId || !rootsReady) return;
        if (findNode(rootsRef.current, Number(currentFolderId))) return;
        // One attempt per folder id — if the chain fetch fails (or the id is
        // stale/deleted), don't refetch on every roots change.
        if (handledDeepLinkRef.current === currentFolderId) return;
        handledDeepLinkRef.current = currentFolderId;

        let cancelled = false;
        let completed = false;
        (async () => {
            try {
                const parentPath = await getFolderParentPathApi(String(knowledgeId), currentFolderId);
                if (cancelled || !parentPath?.length) return;
                const ancestorIds = new Set(parentPath.map((p) => Number(p.id)));
                // Walk the current tree along the ancestor chain, reusing children
                // that are already loaded and fetching only the missing levels.
                const expandChain = async (nodes: TreeNode[]): Promise<TreeNode[]> => {
                    return Promise.all(nodes.map(async (n) => {
                        if (!ancestorIds.has(n.id)) return n;
                        try {
                            let children = n.children;
                            if (!Array.isArray(children)) {
                                const { items } = await listKnowledgeFolders({
                                    space_id: knowledgeId, parent_id: n.id, file_status: fileStatus,
                                });
                                children = mapToTree(items);
                            }
                            return { ...n, expanded: true, loading: false, children: await expandChain(children) };
                        } catch {
                            return { ...n, expanded: true, loading: false, children: n.children ?? [] };
                        }
                    }));
                };
                const fresh = await expandChain(rootsRef.current);
                if (!cancelled) setRoots(fresh);
            } catch {
                // ignore — leave the tree as is; the user can expand manually.
            } finally {
                completed = true;
            }
        })();
        return () => {
            cancelled = true;
            // A run cancelled mid-flight (deps changed, StrictMode double-mount)
            // didn't actually expand anything — release the once-per-id mark so
            // the next run for this folder id can try again.
            if (!completed && handledDeepLinkRef.current === currentFolderId) {
                handledDeepLinkRef.current = null;
            }
        };
    }, [knowledgeId, fileStatus, currentFolderId, rootsReady]);

    // Re-fetch a freshly-loaded subtree, re-expanding nodes that were open before.
    const rebuildWithExpansion = useCallback(async (
        nodes: TreeNode[],
        expandedIds: Set<number>,
    ): Promise<TreeNode[]> => {
        return Promise.all(nodes.map(async (n) => {
            if (!expandedIds.has(n.id)) return n;
            try {
                const { items } = await listKnowledgeFolders({
                    space_id: knowledgeId, parent_id: n.id, file_status: fileStatus,
                });
                const children = await rebuildWithExpansion(mapToTree(items), expandedIds);
                return { ...n, expanded: true, loading: false, children };
            } catch {
                return { ...n, expanded: true, loading: false, children: [] };
            }
        }));
    }, [knowledgeId, fileStatus]);

    /** Full tree refresh that preserves which nodes were expanded. */
    const refreshTree = useCallback(async () => {
        if (!knowledgeId) return;
        const expandedIds = collectExpandedIds(rootsRef.current, new Set<number>());
        try {
            const { items } = await listKnowledgeFolders({
                space_id: knowledgeId, parent_id: null, file_status: fileStatus,
            });
            const fresh = await rebuildWithExpansion(mapToTree(items), expandedIds);
            setRoots(fresh);
        } catch {
            // Keep the current tree on failure — a stale tree beats an empty one.
        }
    }, [knowledgeId, fileStatus, rebuildWithExpansion]);

    // Refresh when the right-side panel reports a folder change for this space.
    useEffect(() => {
        const handler = (e: Event) => {
            const detail = (e as CustomEvent<KnowledgeSpaceFilesRefreshEventDetail>).detail;
            // No spaceId → global refresh; otherwise only react to our own space.
            if (detail?.spaceId != null && String(detail.spaceId) !== String(knowledgeId)) {
                return;
            }
            refreshTree();
        };
        window.addEventListener(KNOWLEDGE_SPACE_FILES_REFRESH_EVENT, handler);
        return () => window.removeEventListener(KNOWLEDGE_SPACE_FILES_REFRESH_EVENT, handler);
    }, [knowledgeId, refreshTree]);

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
                    compact={compact}
                />
            ))}
        </div>
    );
}
