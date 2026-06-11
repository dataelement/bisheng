import { useQuery } from "@tanstack/react-query";
import { ChevronRight, File as FileIcon, Folder as FolderIcon, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
    FileType,
    getSpaceChildrenApi,
    SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED,
    type KnowledgeFile,
} from "~/api/knowledge";
import { listUploadableSpacesApi } from "~/api/messageExport";
import { Button } from "~/components/ui/Button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "~/components/ui/Dialog";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

interface MoveToDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** Source space — pinned first in the list and labelled "current". */
    currentSpaceId: string;
    currentSpaceName: string;
    /**
     * Resolve the chosen target and run the move. The dialog only picks a
     * destination; conflict/undo/confirm handling lives in the caller (T011).
     * Returning a promise keeps the button busy until the move settles.
     */
    onConfirm: (
        targetSpaceId: string,
        targetFolderId: string | null,
        crossSpace: boolean,
        targetFolderName?: string,
    ) => Promise<void> | void;
}

interface FolderCrumb {
    id: string;
    name: string;
}

export function MoveToDialog({
    open,
    onOpenChange,
    currentSpaceId,
    currentSpaceName,
    onConfirm,
}: MoveToDialogProps) {
    const localize = useLocalize();
    const [selectedSpaceId, setSelectedSpaceId] = useState(currentSpaceId);
    const [folderStack, setFolderStack] = useState<FolderCrumb[]>([]);
    const [submitting, setSubmitting] = useState(false);

    const currentFolderId = folderStack.length ? folderStack[folderStack.length - 1].id : null;
    const crossSpace = selectedSpaceId !== currentSpaceId;

    // Reset to the source space root on every open — the picker should never
    // reopen deep inside a folder the user browsed to last time.
    useEffect(() => {
        if (open) {
            setSelectedSpaceId(currentSpaceId);
            setFolderStack([]);
        }
    }, [open, currentSpaceId]);

    const { data: uploadable = [] } = useQuery({
        queryKey: ["move-uploadable-spaces"],
        queryFn: () => listUploadableSpacesApi(),
        enabled: open,
    });

    // Current (source) space pinned first; uploadable spaces follow (deduped).
    const spaces = useMemo(() => {
        const others = uploadable
            .filter((s) => s.id !== currentSpaceId)
            .map((s) => ({ id: s.id, name: s.name }));
        return [{ id: currentSpaceId, name: currentSpaceName }, ...others];
    }, [uploadable, currentSpaceId, currentSpaceName]);

    const { data: children, isLoading } = useQuery({
        queryKey: ["move-children", selectedSpaceId, currentFolderId],
        queryFn: () =>
            getSpaceChildrenApi({
                space_id: selectedSpaceId,
                parent_id: currentFolderId ?? undefined,
                page_size: 200,
                file_status: SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED,
            }),
        enabled: open && !!selectedSpaceId,
    });
    const items: KnowledgeFile[] = children?.data ?? [];
    const folders = items.filter((it) => it.type === FileType.FOLDER);
    const files = items.filter((it) => it.type !== FileType.FOLDER);

    const handleSelectSpace = (id: string) => {
        setSelectedSpaceId(id);
        setFolderStack([]);
    };

    const handleEnterFolder = (f: KnowledgeFile) => {
        setFolderStack((stack) => [...stack, { id: f.id, name: f.name }]);
    };

    // idx = number of crumbs to keep (0 = root).
    const handleBreadcrumb = (keep: number) => {
        setFolderStack((stack) => stack.slice(0, keep));
    };

    const handleConfirm = async () => {
        setSubmitting(true);
        try {
            const targetFolderName = folderStack.length ? folderStack[folderStack.length - 1].name : undefined;
            await onConfirm(selectedSpaceId, currentFolderId, crossSpace, targetFolderName);
            onOpenChange(false);
        } catch {
            // Caller surfaced the reason (cancelled confirm / hard error);
            // keep the dialog open so the user can adjust or retry.
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle>{localize("com_knowledge.move_to")}</DialogTitle>
                </DialogHeader>

                <div className="flex h-80 overflow-hidden rounded-md border border-border-light">
                    {/* Left: destination spaces */}
                    <div className="w-48 shrink-0 overflow-y-auto border-r border-border-light">
                        {spaces.map((s) => (
                            <button
                                key={s.id}
                                type="button"
                                onClick={() => handleSelectSpace(s.id)}
                                className={cn(
                                    "flex w-full items-center truncate px-3 py-2 text-left text-sm hover:bg-accent",
                                    s.id === selectedSpaceId && "bg-accent font-medium",
                                )}
                                title={s.name}
                            >
                                <span className="truncate">{s.name}</span>
                                {s.id === currentSpaceId && (
                                    <span className="ml-1 shrink-0 text-xs text-text-secondary">
                                        {localize("com_knowledge.current_space_tag")}
                                    </span>
                                )}
                            </button>
                        ))}
                    </div>

                    {/* Right: folder navigation within the selected space */}
                    <div className="flex flex-1 flex-col">
                        <div className="flex flex-wrap items-center gap-0.5 border-b border-border-light px-3 py-2 text-sm">
                            <button
                                type="button"
                                className="hover:text-primary"
                                onClick={() => handleBreadcrumb(0)}
                            >
                                {localize("com_knowledge.root_dir")}
                            </button>
                            {folderStack.map((f, i) => (
                                <span key={f.id} className="flex items-center gap-0.5">
                                    <ChevronRight className="size-3.5 text-text-secondary" />
                                    <button
                                        type="button"
                                        className="max-w-[10rem] truncate hover:text-primary"
                                        onClick={() => handleBreadcrumb(i + 1)}
                                        title={f.name}
                                    >
                                        {f.name}
                                    </button>
                                </span>
                            ))}
                        </div>

                        <div className="flex-1 overflow-y-auto py-1">
                            {isLoading ? (
                                <div className="flex h-full items-center justify-center text-text-secondary">
                                    <Loader2 className="size-5 animate-spin" />
                                </div>
                            ) : folders.length === 0 && files.length === 0 ? (
                                <div className="flex h-full items-center justify-center text-sm text-text-secondary">
                                    {localize("com_knowledge.move_empty_folder")}
                                </div>
                            ) : (
                                <>
                                    {folders.map((f) => (
                                        <button
                                            key={f.id}
                                            type="button"
                                            onClick={() => handleEnterFolder(f)}
                                            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent"
                                        >
                                            <FolderIcon className="size-4 shrink-0 text-primary" />
                                            <span className="flex-1 truncate">{f.name}</span>
                                            <ChevronRight className="size-4 shrink-0 text-text-secondary" />
                                        </button>
                                    ))}
                                    {/* Files cannot be a move target — shown disabled for context. */}
                                    {files.map((f) => (
                                        <div
                                            key={f.id}
                                            className="flex w-full items-center gap-2 px-3 py-1.5 text-sm opacity-40"
                                        >
                                            <FileIcon className="size-4 shrink-0" />
                                            <span className="flex-1 truncate">{f.name}</span>
                                        </div>
                                    ))}
                                </>
                            )}
                        </div>
                    </div>
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
                        {localize("cancel")}
                    </Button>
                    <Button onClick={handleConfirm} disabled={submitting}>
                        {submitting && <Loader2 className="mr-1 size-4 animate-spin" />}
                        {localize("com_knowledge.move_here")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
