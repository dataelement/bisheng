import { useLocalize } from "~/hooks";
import { BookCopyIcon, ChevronDown, ChevronRight, FolderClosedIcon, Loader2, Plus, Search, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { NotificationSeverity } from "~/common";
import { Input } from "~/components";
import { Button } from "~/components/ui/Button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui/Dialog";
import { useToastContext } from "~/Providers";
import { generateUUID } from "~/utils";
import {
    getMineSpacesApi,
    getSpaceChildrenApi,
    createFolderApi,
    addArticleToKnowledgeApi,
    FileType,
} from "~/api/knowledge";
import { ChannelNotebookOneIcon } from "~/components/icons/channels";

// ─── Types ─────────────────────────────────────────────────────────────

export interface KnowledgeNode {
    id: string;
    name: string;
    type: "space" | "folder";
    level: number;       // 1 = knowledge space, 2+ = folder
    parentId: string | null;
    /** The space_id this node belongs to (for API calls) */
    spaceId: string;
    children?: KnowledgeNode[];
    /** Whether children have been loaded from the API */
    childrenLoaded?: boolean;
    /** Whether children are currently loading */
    childrenLoading?: boolean;
}

interface AddToKnowledgeModalProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** Article ID to add to the selected knowledge space/folder */
    articleId?: string | number;
}

// ─── Helpers ─────────────────────────────────────────────────────────────

/** Deep copy tree */
function cloneTree(nodes: KnowledgeNode[]): KnowledgeNode[] {
    return nodes.map(n => ({ ...n, children: n.children ? cloneTree(n.children) : [] }));
}

/** Find node in tree and execute operation */
function mapTree(
    nodes: KnowledgeNode[],
    predicate: (n: KnowledgeNode) => boolean,
    transform: (n: KnowledgeNode) => KnowledgeNode
): KnowledgeNode[] {
    return nodes.map(n => {
        if (predicate(n)) return transform(n);
        return { ...n, children: n.children ? mapTree(n.children, predicate, transform) : [] };
    });
}

/** Recursively filter matching nodes, preserving ancestor paths */
function filterTree(nodes: KnowledgeNode[], keyword: string): KnowledgeNode[] {
    const kw = keyword.toLowerCase();
    return nodes.reduce<KnowledgeNode[]>((acc, node) => {
        const filteredChildren = filterTree(node.children ?? [], keyword);
        const matches = node.name.toLowerCase().includes(kw);
        if (matches || filteredChildren.length > 0) {
            acc.push({ ...node, children: filteredChildren });
        }
        return acc;
    }, []);
}

/** Find a node by id recursively */
function findNode(nodes: KnowledgeNode[], id: string): KnowledgeNode | undefined {
    for (const n of nodes) {
        if (n.id === id) return n;
        if (n.children) {
            const found = findNode(n.children, id);
            if (found) return found;
        }
    }
    return undefined;
}

// ─── Inline Editing Input ─────────────────────────────────────────────

interface InlineEditProps {
    defaultValue: string;
    onSave: (name: string) => void;
    onCancel: () => void;
    onValidate: (name: string) => boolean;
}

function InlineEdit({ defaultValue, onSave, onCancel, onValidate }: InlineEditProps) {
    const ref = useRef<HTMLInputElement>(null);
    const [value, setValue] = useState(defaultValue);

    useEffect(() => {
        if (ref.current) {
            ref.current.focus();
            ref.current.select();
        }
    }, []);

    const commit = () => {
        const trimmed = value.trim();
        if (!trimmed) {
            onCancel();
            return;
        }
        if (trimmed.length > 50) {
            onCancel();
            return;
        }
        if (!onValidate(trimmed)) {
            onCancel();
            return;
        }
        onSave(trimmed);
    };

    return (
        <input
            ref={ref}
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={e => {
                if (e.key === "Enter") { e.preventDefault(); commit(); }
                if (e.key === "Escape") { e.preventDefault(); onCancel(); }
            }}
            onBlur={commit}
            maxLength={50}
            className="flex-1 min-w-0 border border-primary rounded px-1.5 py-0 text-sm outline-none bg-white text-primary"
            onClick={e => e.stopPropagation()}
        />
    );
}

// ─── Tree Node Row ─────────────────────────────────────────────────────

interface TreeNodeProps {
    node: KnowledgeNode;
    nodes: KnowledgeNode[];
    selectedId: string | null;
    expandedIds: Set<string>;
    editingId: string | null;
    onSelect: (id: string) => void;
    onToggle: (id: string) => void;
    onAddFolder: (parentId: string, parentLevel: number, spaceId: string) => void;
    onSaveEdit: (id: string, name: string) => void;
    onCancelEdit: () => void;
    searchMode: boolean;
}

function TreeNode({
    node, nodes, selectedId, expandedIds, editingId,
    onSelect, onToggle, onAddFolder, onSaveEdit, onCancelEdit, searchMode
}: TreeNodeProps) {
    const localize = useLocalize();
    const isExpanded = searchMode || expandedIds.has(node.id);
    const isSelected = selectedId === node.id;
    const isEditing = editingId === node.id;
    // Show expand arrow for spaces (always expandable) or folders with known children
    const hasOrMayHaveChildren = node.type === "space" || (node.children?.length ?? 0) > 0 || !node.childrenLoaded;
    const indent = (node.level - 1) * 16;

    const { showToast } = useToastContext();

    return (
        <div>
            <div
                className={`group flex items-center gap-1.5 py-1 px-2 rounded-md cursor-pointer text-sm transition-colors select-none
                    ${isSelected ? "bg-[#EEF2FF] text-primary" : "hover:bg-gray-50"}`}
                style={{ paddingLeft: `${indent + 8}px` }}
                onClick={() => onSelect(node.id)}
            >
                {/* Expand toggle */}
                <span
                    className="shrink-0 size-4 flex items-center justify-center text-[#86909c]"
                    onClick={e => { e.stopPropagation(); onToggle(node.id); }}
                >
                    {node.childrenLoading
                        ? <Loader2 className="size-3 animate-spin" />
                        : hasOrMayHaveChildren
                            ? (isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />)
                            : <span className="size-3.5" />}
                </span>

                {/* Icon */}
                {node.type === "space"
                    ?
                    <ChannelNotebookOneIcon className="size-[14px] object-contain opacity-90" />
                    : <FolderClosedIcon className={`shrink-0 size-3.5 ${isSelected ? "text-primary" : "text-[#4e5969]"}`} />
                }

                {/* Name / Inline edit */}
                {isEditing ? (
                    <InlineEdit
                        defaultValue={node.name}
                        onValidate={(name) => {
                            if (nodes.some(node => node.name === name)) {
                                showToast({ message: "Name cannot be identical to existing folder", severity: NotificationSeverity.WARNING });
                                return false;
                            }
                            return true;
                        }}
                        onSave={(name) => onSaveEdit(node.id, name)}
                        onCancel={onCancelEdit}
                    />
                ) : (
                    <span className="flex-1 truncate">{node.name}</span>
                )}

                {/* Add folder button (hover) */}
                {!isEditing && (
                    <button
                        className="shrink-0 opacity-0 group-hover:opacity-100 size-4 flex items-center justify-center rounded hover:bg-[#dce4ff] text-[#86909c] hover:text-primary transition-all"
                        title={localize("com_subscription.new_subfolder")}
                        onClick={e => { e.stopPropagation(); onAddFolder(node.id, node.level, node.spaceId); }}
                    >
                        <Plus className="size-4 text-primary" />
                    </button>
                )}
            </div>

            {/* Children */}
            {isExpanded && node.children && node.children.length > 0 && (
                <div>
                    {node.children.map(child => (
                        <TreeNode
                            key={child.id}
                            node={child}
                            nodes={node.children || []}
                            selectedId={selectedId}
                            expandedIds={expandedIds}
                            editingId={editingId}
                            onSelect={onSelect}
                            onToggle={onToggle}
                            onAddFolder={onAddFolder}
                            onSaveEdit={onSaveEdit}
                            onCancelEdit={onCancelEdit}
                            searchMode={searchMode}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}

// ─── Main Modal ──────────────────────────────────────────────────────────

export function AddToKnowledgeModal({ open, onOpenChange, articleId }: AddToKnowledgeModalProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [tree, setTree] = useState<KnowledgeNode[]>([]);
    const [search, setSearch] = useState("");
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
    const [editingId, setEditingId] = useState<string | null>(null);
    const [isConfirming, setIsConfirming] = useState(false);
    const [spacesLoading, setSpacesLoading] = useState(false);

    // Filtered tree by search
    const displayTree = search.trim() ? filterTree(tree, search) : tree;
    const isSearchMode = !!search.trim();

    // ─── Load spaces list on open ──────────────────────────────
    useEffect(() => {
        if (!open) return;
        setSpacesLoading(true);
        getMineSpacesApi()
            .then((spaces) => {
                const nodes: KnowledgeNode[] = spaces.map(s => ({
                    id: s.id,
                    name: s.name,
                    type: "space" as const,
                    level: 1,
                    parentId: null,
                    spaceId: s.id,
                    children: [],
                    childrenLoaded: false,
                }));
                setTree(nodes);
            })
            .catch(() => showToast({ message: "加载空间列表失败", severity: NotificationSeverity.ERROR }))
            .finally(() => setSpacesLoading(false));
    }, [open]);

    // ─── Lazy-load children on expand ─────────────────────────
    const loadChildren = useCallback(async (nodeId: string) => {
        const node = findNode(tree, nodeId);
        if (!node || node.childrenLoaded || node.childrenLoading) return;

        // Mark loading
        setTree(prev => mapTree(prev, n => n.id === nodeId, n => ({ ...n, childrenLoading: true })));

        try {
            const parentId = node.type === "space" ? undefined : nodeId;
            const res = await getSpaceChildrenApi({
                space_id: node.spaceId,
                parent_id: parentId,
                page_size: 200,
            });

            // Only keep folders for the tree
            const folderChildren: KnowledgeNode[] = res.data
                .filter(f => f.type === FileType.FOLDER)
                .map(f => ({
                    id: f.id,
                    name: f.name,
                    type: "folder" as const,
                    level: node.level + 1,
                    parentId: nodeId,
                    spaceId: node.spaceId,
                    children: [],
                    childrenLoaded: false,
                }));

            setTree(prev => mapTree(prev, n => n.id === nodeId, n => ({
                ...n,
                // Merge: keep any locally-created "new-folder-*" nodes AND add API results
                children: [
                    ...(n.children?.filter(c => c.id.startsWith("new-folder-")) ?? []),
                    ...folderChildren,
                ],
                childrenLoaded: true,
                childrenLoading: false,
            })));
        } catch {
            setTree(prev => mapTree(prev, n => n.id === nodeId, n => ({ ...n, childrenLoading: false })));
        }
    }, [tree]);

    const toggleExpand = useCallback((id: string) => {
        setExpandedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
                // Trigger lazy-load
                loadChildren(id);
            }
            return next;
        });
    }, [loadChildren]);

    const handleSelect = (id: string) => {
        if (editingId) return;
        setSelectedId(id);
    };

    /** Create folder via API */
    const handleAddFolder = async (parentId: string, parentLevel: number, spaceId: string) => {
        if (parentLevel >= 10) {
            showToast({ message: "Folder limit 10 levels reached", severity: NotificationSeverity.WARNING });
            return;
        }
        const code = generateUUID(12).toLocaleUpperCase()
        const tempId = `new-folder-${Date.now()}`;
        const defaultName = localize("com_subscription.unnamed_folder_code", { code });

        // Optimistic UI: insert a temporary node
        const tempNode: KnowledgeNode = {
            id: tempId,
            name: defaultName,
            type: "folder",
            level: parentLevel + 1,
            parentId,
            spaceId,
            children: [],
            childrenLoaded: true,
        };

        setTree(prev => mapTree(prev, n => n.id === parentId, n => ({
            ...n,
            children: [...(n.children ?? []), tempNode],
        })));
        setExpandedIds(prev => new Set([...prev, parentId]));
        setEditingId(tempId);
        setSelectedId(tempId);
    };

    /** Save folder name — creates via API */
    const handleSaveEdit = async (id: string, name: string) => {
        if (name.length > 50) {
            showToast({ message: "Name cannot exceed 50 characters", severity: NotificationSeverity.WARNING });
            return;
        }

        const node = findNode(tree, id);
        if (!node) return;

        // If it's a newly created temp node, call createFolder API
        if (id.startsWith("new-folder-")) {
            try {
                // Determine the real parent_id: if parent is a space, parent_id is null
                const parentNode = node.parentId ? findNode(tree, node.parentId) : null;
                const apiParentId = parentNode?.type === "space" ? null : node.parentId;

                const created = await createFolderApi(node.spaceId, {
                    name,
                    parent_id: apiParentId,
                });

                // Replace temp node with real node
                setTree(prev => mapTree(prev, n => n.id === id, () => ({
                    id: created.id,
                    name: created.name || name,
                    type: "folder" as const,
                    level: node.level,
                    parentId: node.parentId,
                    spaceId: node.spaceId,
                    children: [],
                    childrenLoaded: true,
                })));
                setSelectedId(created.id);
            } catch {
                showToast({ message: "创建文件夹失败", severity: NotificationSeverity.ERROR });
                // Remove the temp node
                setTree(prev => {
                    function removeNode(nodes: KnowledgeNode[]): KnowledgeNode[] {
                        return nodes
                            .filter(n => n.id !== id)
                            .map(n => ({ ...n, children: n.children ? removeNode(n.children) : [] }));
                    }
                    return removeNode(prev);
                });
            }
        } else {
            // Just update name in local tree (rename not needed here)
            setTree(prev => mapTree(prev, n => n.id === id, n => ({ ...n, name })));
        }
        setEditingId(null);
    };

    /** Cancel editing (remove newly created temp node) */
    const handleCancelEdit = () => {
        if (editingId?.startsWith("new-folder-")) {
            function removeNode(nodes: KnowledgeNode[]): KnowledgeNode[] {
                return nodes
                    .filter(n => n.id !== editingId)
                    .map(n => ({ ...n, children: n.children ? removeNode(n.children) : [] }));
            }
            setTree(prev => removeNode(prev));
            if (selectedId === editingId) setSelectedId(null);
        }
        setEditingId(null);
    };

    /** Confirm — add article to selected space/folder */
    const handleConfirm = async () => {
        if (!selectedId || !articleId) return;
        setIsConfirming(true);

        // Find the selected node to determine spaceId and folderId
        const node = findNode(tree, selectedId);
        if (!node) { setIsConfirming(false); return; }

        const spaceId = node.spaceId;
        // If selected a space (root), parent_id = null; if a folder, parent_id = folderId
        const parentFolderId = node.type === "space" ? null : selectedId;

        try {
            await addArticleToKnowledgeApi(spaceId, [String(articleId)], parentFolderId);
            showToast({ message: "已添加到知识空间", severity: NotificationSeverity.SUCCESS });
            onOpenChange(false);
        } catch {
            showToast({ message: "添加失败", severity: NotificationSeverity.ERROR });
        } finally {
            setIsConfirming(false);
        }
    };

    // Reset on close
    const handleOpenChange = (val: boolean) => {
        if (!val) {
            setSearch("");
            setSelectedId(null);
            setEditingId(null);
            setExpandedIds(new Set());
            setTree([]);
        }
        onOpenChange(val);
    };

    const isEmpty = !spacesLoading && tree.length === 0;

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent className="w-[600px] max-w-[90vw] p-0 gap-0 overflow-hidden rounded-xl">
                {/* Header */}
                <DialogHeader className="px-6 pt-3 pb-3">
                    <DialogTitle className="font-semibold text-gray-800 leading-6">{localize("com_subscription.add_to_knowledge_space")}</DialogTitle>
                </DialogHeader>

                {/* Search */}
                <div className="px-6 pt-3">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-gray-400 pointer-events-none" />
                        <Input
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            placeholder={localize("com_subscription.search_knowledge_space_placeholder")}
                            className="w-full h-8 pl-8 pr-8 text-sm rounded-md border border-gray-100 focus:outline-none"
                        />
                        {search && (
                            <button
                                className="absolute right-2.5 top-1/2 -translate-y-1/2"
                                onClick={() => setSearch("")}
                            >
                                <X className="size-3.5 text-gray-400" />
                            </button>
                        )}
                    </div>
                </div>

                {/* Tree / Empty state */}
                <div className="px-6 pt-4">
                    <div className="p-3 w-[552px] overflow-auto border rounded-md" style={{ height: 340 }}>
                        {spacesLoading ? (
                            <div className="flex items-center justify-center h-full text-[#86909c]">
                                <Loader2 className="size-5 animate-spin mr-2" />加载中...
                            </div>
                        ) : isEmpty ? (
                            <div className="flex flex-col items-center justify-center h-full text-gray-800">
                                <img
                                    className="size-[120px] mb-4 object-contain opacity-90"
                                    src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                    alt="empty"
                                />
                                <p className="text-sm">{localize("com_subscription.no_selectable_knowledge_space")}</p>
                            </div>
                        ) : displayTree.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-full text-gray-800">
                                <img
                                    className="size-[120px] mb-4 object-contain opacity-90"
                                    src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                    alt="empty"
                                />
                                <p className="text-sm">{localize("com_subscription.no_matching_knowledge_space")}</p>
                            </div>
                        ) : (
                            <div className="py-1">
                                {displayTree.map(node => (
                                    <TreeNode
                                        key={node.id}
                                        node={node}
                                        nodes={displayTree}
                                        selectedId={selectedId}
                                        expandedIds={expandedIds}
                                        editingId={editingId}
                                        onSelect={handleSelect}
                                        onToggle={toggleExpand}
                                        onAddFolder={handleAddFolder}
                                        onSaveEdit={handleSaveEdit}
                                        onCancelEdit={handleCancelEdit}
                                        searchMode={isSearchMode}
                                    />
                                ))}
                            </div>
                        )}
                    </div>
                </div>

                {/* Footer */}
                <DialogFooter className="px-5 py-3.5 mt-3 flex flex-row justify-end gap-1">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleOpenChange(false)}
                        className="h-8 px-4 text-sm rounded-md font-normal"
                    >{localize("com_subscription.cancel")}</Button>
                    <Button
                        size="sm"
                        onClick={handleConfirm}
                        disabled={!selectedId || isConfirming}
                        className="h-8 px-4 text-sm rounded-md font-normal"
                    >
                        {isConfirming && <Loader2 className="size-3.5 mr-1.5 animate-spin" />}{localize("com_subscription.add")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
