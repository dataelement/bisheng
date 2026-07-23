import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { ChevronRight, Folder, FolderPlus, Home, Loader2, Pencil } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, Button } from "~/components/ui";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { getSpaceChildrenApi, createFolderApi, renameFolderApi, KnowledgeFile, FileType } from "~/api/knowledge";
import { dispatchKnowledgeSpaceFilesRefresh } from "../hooks/useFileManager";

interface BreadcrumbItem {
    id: string | null;
    name: string;
}

interface Props {
    open: boolean;
    spaceId: string;
    /** ID of the item being moved (to exclude from selectable targets). */
    movingItemId?: string;
    movingItemType?: "file" | "folder";
    /** Batch move: exclude all selected folder IDs from target picker. */
    excludeFolderIds?: string[];
    /** Batch move: show count in dialog title. */
    movingItemCount?: number;
    onConfirm: (targetFolderId: number | null) => void;
    onCancel: () => void;
    /**
     * Called after a folder is created in the dialog. Lets the host refresh its
     * own file list — needed on the portal, which manages the list itself and
     * does not listen to the global files-refresh event.
     */
    onFolderCreated?: () => void;
}

export function MoveFolderDialog({
    open,
    spaceId,
    movingItemId = "",
    movingItemType = "file",
    excludeFolderIds = [],
    movingItemCount,
    onConfirm,
    onCancel,
    onFolderCreated,
}: Props) {
    const localize = useLocalize();
    const excludedFolderIdSet = useMemo(() => {
        const ids = new Set(excludeFolderIds);
        if (movingItemType === "folder" && movingItemId) {
            ids.add(movingItemId);
        }
        return ids;
    }, [excludeFolderIds, movingItemId, movingItemType]);

    // Currently browsed folder id (null = root)
    const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
    // Breadcrumb trail
    const [breadcrumb, setBreadcrumb] = useState<BreadcrumbItem[]>([{ id: null, name: localize("com_knowledge.root_directory") }]);
    // Folder list at current level
    const [folders, setFolders] = useState<KnowledgeFile[]>([]);
    const [loading, setLoading] = useState(false);
    // Selected target: undefined = not chosen; null = root; string = folder id
    const [selected, setSelected] = useState<string | null | undefined>(undefined);
    // Inline "new folder" creation: null = not creating; string = the editable name
    const [creatingName, setCreatingName] = useState<string | null>(null);
    const [savingFolder, setSavingFolder] = useState(false);
    // Guards against double-submit when Enter and blur both fire
    const submittingRef = useRef(false);
    // Inline rename: null = not renaming; string = the folder id being renamed
    const [renamingId, setRenamingId] = useState<string | null>(null);
    const [renamingName, setRenamingName] = useState("");
    // Guards against double-submit when Enter and blur both fire (rename)
    const renameSubmittingRef = useRef(false);

    const loadFolders = useCallback(async (parentId: string | null) => {
        setLoading(true);
        try {
            const res = await getSpaceChildrenApi({
                space_id: spaceId,
                parent_id: parentId ?? undefined,
                page_size: 200,
            });
            // Only show folders, exclude items being moved (to prevent moving into themselves)
            const filteredFolders = res.data.filter(
                (item) => item.type === FileType.FOLDER && !excludedFolderIdSet.has(item.id)
            );
            setFolders(filteredFolders);
        } catch {
            setFolders([]);
        } finally {
            setLoading(false);
        }
    }, [spaceId, excludedFolderIdSet]);

    // Reset state when dialog opens
    useEffect(() => {
        if (open) {
            setCurrentFolderId(null);
            setBreadcrumb([{ id: null, name: localize("com_knowledge.root_directory") }]);
            setSelected(undefined);
            setCreatingName(null);
            setRenamingId(null);
            loadFolders(null);
        }
    }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps

    const handleNavigateInto = (folder: KnowledgeFile) => {
        setCurrentFolderId(folder.id);
        setBreadcrumb(prev => [...prev, { id: folder.id, name: folder.name || folder.id }]);
        setSelected(undefined);
        setCreatingName(null);
        setRenamingId(null);
        loadFolders(folder.id);
    };

    const handleBreadcrumbClick = (item: BreadcrumbItem, index: number) => {
        setCurrentFolderId(item.id);
        setBreadcrumb(prev => prev.slice(0, index + 1));
        setSelected(undefined);
        setCreatingName(null);
        setRenamingId(null);
        loadFolders(item.id);
    };

    // Default folder name mirrors the file-list logic (random suffix, no numeric dedup)
    const genRandomStr = () =>
        (Math.random().toString(36).substring(2, 8).toUpperCase() +
            Math.random().toString(36).substring(2, 8).toUpperCase()).substring(0, 12);

    const handleStartCreate = () => {
        setSelected(undefined);
        setRenamingId(null);
        setCreatingName(localize("com_knowledge.unnamed_folder_random", { 0: genRandomStr() }));
    };

    const handleCancelCreate = () => setCreatingName(null);

    const handleConfirmCreate = async () => {
        if (submittingRef.current || creatingName === null) return;
        const name = creatingName.trim();
        if (!name) { setCreatingName(null); return; }
        submittingRef.current = true;
        setSavingFolder(true);
        try {
            await createFolderApi(spaceId, { name, parent_id: currentFolderId });
            setCreatingName(null);
            await loadFolders(currentFolderId);
            // SpaceDetail page: refresh its file list + left folder tree via the global event.
            dispatchKnowledgeSpaceFilesRefresh(spaceId);
            // Portal (and any host that manages its own list): refresh through the callback.
            onFolderCreated?.();
        } catch {
            // Error is surfaced by the response interceptor; keep the row for retry/cancel.
        } finally {
            submittingRef.current = false;
            setSavingFolder(false);
        }
    };

    const handleStartRename = (folder: KnowledgeFile) => {
        // Mutual exclusion with the new-folder editor
        setCreatingName(null);
        setRenamingId(folder.id);
        setRenamingName(folder.name || "");
    };

    const handleCancelRename = () => setRenamingId(null);

    const handleConfirmRename = async (folder: KnowledgeFile) => {
        if (renameSubmittingRef.current || renamingId !== folder.id) return;
        const name = renamingName.trim();
        // No-op when empty or unchanged
        if (!name || name === (folder.name || "")) { setRenamingId(null); return; }
        renameSubmittingRef.current = true;
        setSavingFolder(true);
        try {
            await renameFolderApi(spaceId, folder.id, name);
            setRenamingId(null);
            await loadFolders(currentFolderId);
            // SpaceDetail: refresh its file list + left folder tree via the global event.
            dispatchKnowledgeSpaceFilesRefresh(spaceId);
            // Portal (and any host that manages its own list): refresh through the callback.
            onFolderCreated?.();
        } catch {
            // Error is surfaced by the response interceptor; keep the row for retry/cancel.
        } finally {
            renameSubmittingRef.current = false;
            setSavingFolder(false);
        }
    };

    const handleSelectRoot = () => {
        setSelected(null);
    };

    const handleConfirm = () => {
        if (selected === undefined) return;
        // Backend expects integer folder id or null for root
        onConfirm(selected !== null ? Number(selected) : null);
    };

    const isRootSelected = selected === null;
    const hasSelection = selected !== undefined;

    return (
        <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel(); }}>
            <DialogContent className="max-w-md w-full">
                <DialogHeader>
                    <DialogTitle>
                        {movingItemCount && movingItemCount > 1
                            ? localize("com_knowledge.batch_move_title", { 0: movingItemCount })
                            : localize("com_knowledge.move_to")}
                    </DialogTitle>
                </DialogHeader>

                {/* Breadcrumb + new-folder action (space-between) */}
                <div className="flex items-center justify-between gap-2 px-1 min-h-[28px]">
                    <div className="flex items-center gap-1 flex-wrap text-sm text-[#4e5969]">
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
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={loading || savingFolder || creatingName !== null}
                        onClick={handleStartCreate}
                        className="h-7 shrink-0 px-2 text-[12px] text-[#4e5969]"
                    >
                        <FolderPlus className="mr-1.5 size-4" />
                        {localize("com_knowledge.new_folder")}
                    </Button>
                </div>

                {/* Folder list */}
                <div className="border border-[#e5e6eb] rounded-lg overflow-hidden min-h-[200px] max-h-[320px] overflow-y-auto">
                    {/* Root option (only shown at root level) — always first */}
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

                    {/* Inline new-folder row (below root option, above existing folders) */}
                    {creatingName !== null && (
                        <div className="flex items-center gap-2 px-3 py-2.5 border-b border-[#e5e6eb] text-sm bg-[#f5f6fa]">
                            <Folder className="size-4 shrink-0 text-[#f7ba1e]" />
                            <input
                                autoFocus
                                value={creatingName}
                                disabled={savingFolder}
                                onChange={(e) => setCreatingName(e.target.value)}
                                onFocus={(e) => e.target.select()}
                                onKeyDown={(e) => {
                                    if (e.key === "Enter") {
                                        e.preventDefault();
                                        handleConfirmCreate();
                                    } else if (e.key === "Escape") {
                                        e.preventDefault();
                                        handleCancelCreate();
                                    }
                                }}
                                onBlur={handleConfirmCreate}
                                className="min-w-0 flex-1 rounded border border-[#165dff] bg-white px-2 py-1 text-sm outline-none"
                            />
                            {savingFolder && <Loader2 className="size-4 shrink-0 animate-spin text-[#86909c]" />}
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
                        folders.map((folder) => {
                            const isRenaming = renamingId === folder.id;
                            return (
                                <div
                                    key={folder.id}
                                    onClick={() => { if (!isRenaming) setSelected(folder.id); }}
                                    className={cn(
                                        "flex items-center gap-2 px-3 py-2.5 border-b border-[#e5e6eb] last:border-b-0 text-sm transition-colors group",
                                        isRenaming
                                            ? "bg-[#f5f6fa]"
                                            : selected === folder.id
                                                ? "cursor-pointer bg-[#e8f3ff] text-[#165dff]"
                                                : "cursor-pointer hover:bg-[#f5f6fa] text-[#1d2129]"
                                    )}
                                >
                                    <Folder className="size-4 shrink-0 text-[#f7ba1e]" />
                                    {isRenaming ? (
                                        <>
                                            <input
                                                autoFocus
                                                value={renamingName}
                                                disabled={savingFolder}
                                                onChange={(e) => setRenamingName(e.target.value)}
                                                onFocus={(e) => e.target.select()}
                                                onClick={(e) => e.stopPropagation()}
                                                onKeyDown={(e) => {
                                                    if (e.key === "Enter") {
                                                        e.preventDefault();
                                                        handleConfirmRename(folder);
                                                    } else if (e.key === "Escape") {
                                                        e.preventDefault();
                                                        handleCancelRename();
                                                    }
                                                }}
                                                onBlur={() => handleConfirmRename(folder)}
                                                className="min-w-0 flex-1 rounded border border-[#165dff] bg-white px-2 py-1 text-sm outline-none"
                                            />
                                            {savingFolder && <Loader2 className="size-4 shrink-0 animate-spin text-[#86909c]" />}
                                        </>
                                    ) : (
                                        <>
                                            <span className="flex-1 truncate">{folder.name}</span>
                                            {/* Rename this folder */}
                                            <button
                                                type="button"
                                                disabled={savingFolder}
                                                onClick={(e) => { e.stopPropagation(); handleStartRename(folder); }}
                                                className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[#165dff]/10 transition-opacity"
                                                title={localize("com_knowledge.rename")}
                                            >
                                                <Pencil className="size-4 text-[#4e5969]" />
                                            </button>
                                            {/* Navigate into sub-folder */}
                                            <button
                                                type="button"
                                                onClick={(e) => { e.stopPropagation(); handleNavigateInto(folder); }}
                                                className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[#165dff]/10 transition-opacity"
                                                title={localize("com_knowledge.folder")}
                                            >
                                                <ChevronRight className="size-4 text-[#4e5969]" />
                                            </button>
                                        </>
                                    )}
                                </div>
                            );
                        })
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
                        {localize("com_bschoose_confirm")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
