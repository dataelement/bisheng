import { Outlined } from "bisheng-icons";
import { useCallback, useEffect, useState } from "react";

import { listKnowledgeFolders } from "~/api/knowledge";
import { cn } from "~/utils";
import { DynamicEllipsisName } from "../sidebar/DynamicEllipsisName";

// ─── Types ──────────────────────────────────────────────────────────────────

interface TreeNode {
    id: number;
    name: string;
    /** Whether the expand arrow has been clicked at least once. */
    expanded: boolean;
    /** undefined = not yet fetched; [] = fetched but empty. */
    children?: TreeNode[];
    loading?: boolean;
}

export interface FolderSelectPayload {
    id: string;
    name: string;
}

interface MoveToFolderTreeProps {
    knowledgeId: string | number;
    /** Highlight-only selection — never triggers a refetch (unlike the sidebar tree). */
    selectedFolderId?: string | null;
    /** Status filter — mirror the right-side panel (MEMBER role hides FAILED items). */
    fileStatus?: number[];
    onSelectFolder: (folder: FolderSelectPayload) => void;
    /** Indent (px) of this tree's depth-0 rows, so folders align under the space row. */
    baseIndent: number;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mapToTree(nodes: { id: number; file_name: string }[]): TreeNode[] {
    return nodes.map((n) => ({ id: n.id, name: n.file_name, expanded: false, children: undefined }));
}

/** Immutably update a node anywhere in the tree by id. */
function updateNode(nodes: TreeNode[], targetId: number, updater: (n: TreeNode) => TreeNode): TreeNode[] {
    return nodes.map((n) => {
        if (n.id === targetId) return updater(n);
        if (Array.isArray(n.children) && n.children.length > 0) {
            return { ...n, children: updateNode(n.children, targetId, updater) };
        }
        return n;
    });
}

// ─── Single node row ──────────────────────────────────────────────────────────

interface TreeNodeRowProps {
    node: TreeNode;
    depth: number;
    baseIndent: number;
    selectedFolderId?: string | null;
    onExpand: (node: TreeNode) => void;
    onSelect: (node: TreeNode) => void;
}

function TreeNodeRow({ node, depth, baseIndent, selectedFolderId, onExpand, onSelect }: TreeNodeRowProps) {
    const isSelected = selectedFolderId != null && selectedFolderId === String(node.id);
    const hasExpandedChildren = node.expanded && Array.isArray(node.children);

    return (
        <>
            <div
                className={cn(
                    "group flex h-7 cursor-pointer select-none items-center rounded-md pr-1 text-[12px] leading-5 text-[#1d2129] transition-colors hover:bg-[#F4F4F4]",
                    isSelected && "bg-[#EEEEEE] font-semibold hover:bg-[#EEEEEE]",
                )}
                style={{ paddingLeft: `${baseIndent + depth * 20}px` }}
                onClick={() => onSelect(node)}
            >
                {/* Switcher slot: 20×20 wrapper, 16×16 chevron inside */}
                <button
                    type="button"
                    className="flex size-5 shrink-0 items-center justify-center rounded"
                    onClick={(e) => {
                        e.stopPropagation();
                        onExpand(node);
                    }}
                    aria-label={node.expanded ? "Collapse folder" : "Expand folder"}
                >
                    {node.loading ? (
                        <span className="inline-block size-3 animate-spin rounded-full border-2 border-[#8D93A0] border-t-transparent" />
                    ) : (
                        <Outlined.Right
                            className={cn(
                                "size-3.5 text-[#8D93A0] transition-transform duration-150",
                                node.expanded && "rotate-90",
                            )}
                        />
                    )}
                </button>

                {/* Icon wrapper: 20×20 wrapper, 16×16 folder icon inside */}
                <div className="flex size-5 shrink-0 items-center justify-center">
                    {hasExpandedChildren ? (
                        <Outlined.FolderOpen className={cn("size-3.5 shrink-0", isSelected ? "text-[#1d2129]" : "text-[#8D93A0]")} />
                    ) : (
                        <Outlined.FolderClose className={cn("size-3.5 shrink-0", isSelected ? "text-[#1d2129]" : "text-[#8D93A0]")} />
                    )}
                </div>

                <DynamicEllipsisName
                    name={node.name}
                    textClassName={cn("text-[12px] leading-5 text-[#1d2129]", isSelected && "font-semibold")}
                />
            </div>

            {node.expanded && Array.isArray(node.children) && node.children.length > 0 && (
                <div className="flex flex-col gap-0.5">
                    {node.children.map((child) => (
                        <TreeNodeRow
                            key={child.id}
                            node={child}
                            depth={depth + 1}
                            baseIndent={baseIndent}
                            selectedFolderId={selectedFolderId}
                            onExpand={onExpand}
                            onSelect={onSelect}
                        />
                    ))}
                </div>
            )}
        </>
    );
}

// ─── Root component ──────────────────────────────────────────────────────────

/**
 * Lazy folder tree for the MoveToDialog left panel. Unlike the sidebar's
 * KnowledgeFolderTree, selection is a pure highlight prop that never refetches —
 * the dialog navigates by clicking, so a reload-on-select spinner would flicker.
 */
export function MoveToFolderTree({
    knowledgeId,
    selectedFolderId,
    fileStatus,
    onSelectFolder,
    baseIndent,
}: MoveToFolderTreeProps) {
    const [roots, setRoots] = useState<TreeNode[]>([]);
    const [rootLoading, setRootLoading] = useState(false);

    // Load root folders once per space (and when the status filter changes).
    useEffect(() => {
        if (!knowledgeId) return;
        let cancelled = false;
        setRootLoading(true);
        listKnowledgeFolders({ space_id: knowledgeId, parent_id: null, file_status: fileStatus })
            .then(({ items }) => {
                if (!cancelled) setRoots(mapToTree(items));
            })
            .catch(() => {
                if (!cancelled) setRoots([]);
            })
            .finally(() => {
                if (!cancelled) setRootLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [knowledgeId, fileStatus]);

    const handleExpand = useCallback(
        (node: TreeNode) => {
            if (node.expanded) {
                setRoots((prev) => updateNode(prev, node.id, (n) => ({ ...n, expanded: false })));
                return;
            }
            if (Array.isArray(node.children)) {
                setRoots((prev) => updateNode(prev, node.id, (n) => ({ ...n, expanded: true })));
                return;
            }
            setRoots((prev) => updateNode(prev, node.id, (n) => ({ ...n, loading: true })));
            listKnowledgeFolders({ space_id: knowledgeId, parent_id: node.id, file_status: fileStatus })
                .then(({ items }) => {
                    setRoots((prev) =>
                        updateNode(prev, node.id, (n) => ({
                            ...n,
                            expanded: true,
                            loading: false,
                            children: mapToTree(items),
                        })),
                    );
                })
                .catch(() => {
                    setRoots((prev) =>
                        updateNode(prev, node.id, (n) => ({ ...n, expanded: true, loading: false, children: [] })),
                    );
                });
        },
        [knowledgeId, fileStatus],
    );

    const handleSelect = useCallback(
        (node: TreeNode) => onSelectFolder({ id: String(node.id), name: node.name }),
        [onSelectFolder],
    );

    if (rootLoading) {
        return (
            <div className="flex items-center justify-center py-2">
                <span className="inline-block size-4 animate-spin rounded-full border-2 border-[#8D93A0] border-t-transparent" />
            </div>
        );
    }

    if (roots.length === 0) return null;

    return (
        <div className="flex flex-col gap-0.5">
            {roots.map((node) => (
                <TreeNodeRow
                    key={node.id}
                    node={node}
                    depth={0}
                    baseIndent={baseIndent}
                    selectedFolderId={selectedFolderId}
                    onExpand={handleExpand}
                    onSelect={handleSelect}
                />
            ))}
        </div>
    );
}
