import { BookCopyIcon, ChevronDown, ChevronRight, FolderClosedIcon, FolderIcon, LibraryIcon, Loader2, Plus, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NotificationSeverity } from "~/common";
import { Input } from "~/components";
import { Button } from "~/components/ui/Button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui/Dialog";
import { useToastContext } from "~/Providers";
import { generateUUID } from "~/utils";

// ─── Types ─────────────────────────────────────────────────────────────

export interface KnowledgeNode {
    id: string;
    name: string;
    type: "space" | "folder";
    level: number;       // 1 = 知识空间, 2+ = 文件夹
    parentId: string | null;
    children?: KnowledgeNode[];
}

interface AddToKnowledgeModalProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

// ─── Mock Data ──────────────────────────────────────────────────────────

const MOCK_SPACES: KnowledgeNode[] = [
    {
        id: "space-1", name: "政策信息", type: "space", level: 1, parentId: null,
        children: [
            { id: "folder-1-1", name: "人力政策文件", type: "folder", level: 2, parentId: "space-1", children: [] },
            { id: "folder-1-2", name: "财务政策文件", type: "folder", level: 2, parentId: "space-1", children: [] },
        ]
    },
    {
        id: "space-2", name: "财经报告", type: "space", level: 1, parentId: null,
        children: [
            { id: "folder-2-1", name: "进出口数量", type: "folder", level: 2, parentId: "space-2", children: [] },
            {
                id: "folder-2-2", name: "综合报告", type: "folder", level: 2, parentId: "space-2",
                children: [
                    { id: "folder-2-2-1", name: "海关", type: "folder", level: 3, parentId: "folder-2-2", children: [] },
                    { id: "folder-2-2-2", name: "运输", type: "folder", level: 3, parentId: "folder-2-2", children: [] },
                ]
            },
        ]
    },
    {
        id: "space-3", name: "AI产品", type: "space", level: 1, parentId: null,
        children: [
            { id: "folder-3-1", name: "国内产品", type: "folder", level: 2, parentId: "space-3", children: [] },
            { id: "folder-3-2", name: "海外产品", type: "folder", level: 2, parentId: "space-3", children: [] },
        ]
    },
];

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
    onAddFolder: (parentId: string, parentLevel: number) => void;
    onSaveEdit: (id: string, name: string) => void;
    onCancelEdit: () => void;
    searchMode: boolean;
}

function TreeNode({
    node, nodes, selectedId, expandedIds, editingId,
    onSelect, onToggle, onAddFolder, onSaveEdit, onCancelEdit, searchMode
}: TreeNodeProps) {
    const isExpanded = searchMode || expandedIds.has(node.id);
    const isSelected = selectedId === node.id;
    const isEditing = editingId === node.id;
    const hasChildren = (node.children?.length ?? 0) > 0;
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
                    {hasChildren
                        ? (isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />)
                        : <span className="size-3.5" />}
                </span>

                {/* Icon */}
                {node.type === "space"
                    ? <BookCopyIcon className={`shrink-0 size-3.5 ${isSelected ? "text-primary" : "text-[#4e5969]"}`} />
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
                        title="新建子文件夹"
                        onClick={e => { e.stopPropagation(); onAddFolder(node.id, node.level); }}
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

export function AddToKnowledgeModal({ open, onOpenChange }: AddToKnowledgeModalProps) {
    const { showToast } = useToastContext();
    const [tree, setTree] = useState<KnowledgeNode[]>(() => cloneTree(MOCK_SPACES));
    const [search, setSearch] = useState("");
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
    const [editingId, setEditingId] = useState<string | null>(null);
    const [isConfirming, setIsConfirming] = useState(false);

    // Filtered tree by search
    const displayTree = search.trim() ? filterTree(tree, search) : tree;
    const isSearchMode = !!search.trim();

    const toggleExpand = (id: string) => {
        setExpandedIds(prev => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    };

    const handleSelect = (id: string) => {
        if (editingId) return;
        setSelectedId(id);
    };

    /** New folder */
    const handleAddFolder = (parentId: string, parentLevel: number) => {
        if (parentLevel >= 10) {
            showToast({ message: "Folder limit 10 levels reached", severity: NotificationSeverity.WARNING });
            return;
        }
        const code = generateUUID(12).toLocaleUpperCase()
        const newId = `new-folder-${Date.now()}`;
        const newNode: KnowledgeNode = {
            id: newId,
            name: `未命名文件夹_${code}`,
            type: "folder",
            level: parentLevel + 1,
            parentId,
            children: [],
        };

        // Insert into tree
        setTree(prev => mapTree(prev, n => n.id === parentId, n => ({
            ...n,
            children: [...(n.children ?? []), newNode],
        })));

        // Expand parent node
        setExpandedIds(prev => new Set([...prev, parentId]));

        // Enter editing state
        setEditingId(newId);
        setSelectedId(newId);
    };

    /** Save folder name */
    const handleSaveEdit = (id: string, name: string) => {
        if (name.length > 50) {
            showToast({ message: "Name cannot exceed 50 characters", severity: NotificationSeverity.WARNING });
            return;
        }
        setTree(prev => mapTree(prev, n => n.id === id, n => ({ ...n, name })));
        setEditingId(null);
    };

    /** Cancel editing (remove newly created empty node) */
    const handleCancelEdit = () => {
        if (editingId?.startsWith("new-folder-")) {
            // Delete the node just created
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

    /** Confirm add */
    const handleConfirm = async () => {
        if (!selectedId) return;
        setIsConfirming(true);
        // Mock API request
        await new Promise(r => setTimeout(r, 600));
        setIsConfirming(false);
        showToast({ message: "Added to knowledge base", severity: NotificationSeverity.SUCCESS });
        onOpenChange(false);
    };

    // Reset on close
    const handleOpenChange = (val: boolean) => {
        if (!val) {
            setSearch("");
            setSelectedId(null);
            setEditingId(null);
            setExpandedIds(new Set());
        }
        onOpenChange(val);
    };

    const isEmpty = MOCK_SPACES.length === 0;

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent className="w-[600px] max-w-[90vw] p-0 gap-0 overflow-hidden rounded-xl" close={false}>
                {/* Header */}
                <DialogHeader className="px-6 pt-3 pb-3">
                    <DialogTitle className="font-semibold text-gray-800 leading-6">加入知识空间</DialogTitle>
                </DialogHeader>

                {/* Search */}
                <div className="px-6 pt-3">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-gray-400 pointer-events-none" />
                        <Input
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            placeholder="输入知识空间名称进行搜索"
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
                        {isEmpty ? (
                            <div className="flex flex-col items-center justify-center h-full text-gray-800">
                                {/* Empty state illustration */}
                                <img
                                    className="size-[120px] mb-4 object-contain opacity-90"
                                    src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                    alt="empty"
                                />
                                <p className="text-sm">没有任何可选的知识空间</p>
                            </div>
                        ) : displayTree.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-full text-gray-800">
                                <img
                                    className="size-[120px] mb-4 object-contain opacity-90"
                                    src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                    alt="empty"
                                />
                                <p className="text-sm">未找到匹配的知识空间</p>
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
                        className="h-8 px-4 text-sm rounded-md"
                    >
                        取消
                    </Button>
                    <Button
                        size="sm"
                        onClick={handleConfirm}
                        disabled={!selectedId || isConfirming}
                        className="h-8 px-4 text-sm rounded-md"
                    >
                        {isConfirming && <Loader2 className="size-3.5 mr-1.5 animate-spin" />}
                        加入
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
