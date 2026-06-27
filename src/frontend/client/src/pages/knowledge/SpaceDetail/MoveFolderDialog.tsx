import { useState, useEffect, useCallback } from "react";
import { ChevronRight, Folder, Home, Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, Button } from "~/components/ui";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { getKnowledgeSpaceChildrenApi, KnowledgeSpaceChild, FileType } from "~/api/knowledge";

interface BreadcrumbItem {
    id: number | null;
    name: string;
}

interface Props {
    open: boolean;
    spaceId: string;
    /** ID of the item being moved (to exclude from selectable targets). */
    movingItemId: string;
    movingItemType: "file" | "folder";
    onConfirm: (targetFolderId: number | null) => void;
    onCancel: () => void;
}

export function MoveFolderDialog({ open, spaceId, movingItemId, movingItemType, onConfirm, onCancel }: Props) {
    const localize = useLocalize();

    // Currently browsed folder id (null = root)
    const [currentFolderId, setCurrentFolderId] = useState<number | null>(null);
    // Breadcrumb trail
    const [breadcrumb, setBreadcrumb] = useState<BreadcrumbItem[]>([{ id: null, name: localize("com_knowledge.root_directory") }]);
    // Folder list at current level
    const [folders, setFolders] = useState<KnowledgeSpaceChild[]>([]);
    const [loading, setLoading] = useState(false);
    // Selected target: undefined = not chosen; null = root; number = folder id
    const [selected, setSelected] = useState<number | null | undefined>(undefined);

    const loadFolders = useCallback(async (parentId: number | null) => {
        setLoading(true);
        try {
            const res = await getKnowledgeSpaceChildrenApi({
                space_id: spaceId,
                parent_id: parentId ?? undefined,
                page_size: 200,
            });
            // Only show folders, exclude the item being moved (to prevent moving into itself)
            const filteredFolders = res.data.filter(
                (item) => item.type === FileType.FOLDER && String(item.id) !== movingItemId
            );
            setFolders(filteredFolders);
        } catch {
            setFolders([]);
        } finally {
            setLoading(false);
        }
    }, [spaceId, movingItemId]);

    // Reset state when dialog opens
    useEffect(() => {
        if (open) {
            setCurrentFolderId(null);
            setBreadcrumb([{ id: null, name: localize("com_knowledge.root_directory") }]);
            setSelected(undefined);
            loadFolders(null);
        }
    }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps

    const handleNavigateInto = (folder: KnowledgeSpaceChild) => {
        setCurrentFolderId(folder.id);
        setBreadcrumb(prev => [...prev, { id: folder.id, name: folder.file_name || folder.name || String(folder.id) }]);
        setSelected(undefined);
        loadFolders(folder.id);
    };

    const handleBreadcrumbClick = (item: BreadcrumbItem, index: number) => {
        setCurrentFolderId(item.id);
        setBreadcrumb(prev => prev.slice(0, index + 1));
        setSelected(undefined);
        loadFolders(item.id);
    };

    const handleSelectRoot = () => {
        setSelected(null);
    };

    const handleConfirm = () => {
        if (selected === undefined) return;
        onConfirm(selected);
    };

    const isRootSelected = selected === null;
    const isFolderSelected = typeof selected === "number";
    const hasSelection = selected !== undefined;

    return (
        <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel(); }}>
            <DialogContent className="max-w-md w-full">
                <DialogHeader>
                    <DialogTitle>{localize("com_knowledge.move_to")}</DialogTitle>
                </DialogHeader>

                {/* Breadcrumb */}
                <div className="flex items-center gap-1 flex-wrap text-sm text-[#4e5969] px-1 min-h-[28px]">
                    {breadcrumb.map((item, idx) => (
                        <span key={idx} className="flex items-center gap-1">
                            {idx > 0 && <ChevronRight className="size-3.5 text-[#c0c4cc]" />}
                            <button
                                type="button"
                                onClick={() => handleBreadcrumbClick(item, idx)}
                                className={cn(
                                    "hover:text-[#165dff] transition-colors",
                                    idx === breadcrumb.length - 1 ? "text-[#1d2129] font-medium" : "text-[#4e5969]"
                                )}
                            >
                                {idx === 0 ? <Home className="size-3.5 inline mr-0.5" /> : null}
                                {item.name}
                            </button>
                        </span>
                    ))}
                </div>

                {/* Folder list */}
                <div className="border border-[#e5e6eb] rounded-lg overflow-hidden min-h-[200px] max-h-[320px] overflow-y-auto">
                    {/* Root option (only shown at root level) */}
                    {currentFolderId === null && (
                        <div
                            onClick={handleSelectRoot}
                            className={cn(
                                "flex items-center gap-2 px-3 py-2.5 cursor-pointer border-b border-[#e5e6eb] text-sm transition-colors",
                                isRootSelected ? "bg-[#e8f3ff] text-[#165dff]" : "hover:bg-[#f5f6fa] text-[#1d2129]"
                            )}
                        >
                            <Home className="size-4 shrink-0" />
                            <span>{localize("com_knowledge.root_directory")}</span>
                        </div>
                    )}

                    {loading ? (
                        <div className="flex items-center justify-center py-8 text-[#86909c]">
                            <Loader2 className="size-5 animate-spin mr-2" />
                            <span className="text-sm">{localize("com_ui_loading")}</span>
                        </div>
                    ) : folders.length === 0 ? (
                        <div className="flex items-center justify-center py-8 text-[#86909c] text-sm">
                            {localize("com_knowledge.no_sub_folders")}
                        </div>
                    ) : (
                        folders.map((folder) => (
                            <div
                                key={folder.id}
                                onClick={() => setSelected(folder.id)}
                                className={cn(
                                    "flex items-center gap-2 px-3 py-2.5 cursor-pointer border-b border-[#e5e6eb] last:border-b-0 text-sm transition-colors group",
                                    isFolderSelected && selected === folder.id
                                        ? "bg-[#e8f3ff] text-[#165dff]"
                                        : "hover:bg-[#f5f6fa] text-[#1d2129]"
                                )}
                            >
                                <Folder className="size-4 shrink-0 text-[#f7ba1e]" />
                                <span className="flex-1 truncate">{folder.file_name || folder.name}</span>
                                {/* Navigate into sub-folder */}
                                <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); handleNavigateInto(folder); }}
                                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[#165dff]/10 transition-opacity"
                                    title={localize("com_knowledge.folder")}
                                >
                                    <ChevronRight className="size-4 text-[#4e5969]" />
                                </button>
                            </div>
                        ))
                    )}
                </div>

                <DialogFooter className="gap-2">
                    <Button variant="outline" onClick={onCancel}>
                        {localize("com_ui_cancel")}
                    </Button>
                    <Button
                        disabled={!hasSelection}
                        onClick={handleConfirm}
                    >
                        {localize("com_ui_confirm")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
