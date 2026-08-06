import { FileType, type KnowledgeFile } from "~/api/knowledge";

/** Where a dragged folder would land relative to the row under the pointer. */
export type FolderDropPosition = "before" | "after";

/**
 * Resolve the neighbours a dragged folder lands between — the pair the backend needs to
 * compute its new sort weight.
 *
 * Only folders take part in manual ordering: files keep their existing rules and always
 * sort after the folders, so a file is never a valid neighbour or drop target. Anchoring
 * to one would have the backend place the folder against an order it isn't part of.
 */
export function resolveFolderReorderNeighbours(
    rows: KnowledgeFile[],
    draggedId: string,
    targetId: string,
    position: FolderDropPosition,
): { prevFolderId: string | null; nextFolderId: string | null } | null {
    if (draggedId === targetId) return null;

    const folders = rows.filter((row) => row.type === FileType.FOLDER && !row.isCreating);
    const dragged = folders.find((row) => row.id === draggedId);
    const target = folders.find((row) => row.id === targetId);
    if (!dragged || !target) return null;

    const remaining = folders.filter((row) => row.id !== draggedId);
    const targetIndex = remaining.findIndex((row) => row.id === targetId);
    if (targetIndex < 0) return null;

    const insertAt = position === "before" ? targetIndex : targetIndex + 1;
    return {
        prevFolderId: remaining[insertAt - 1]?.id ?? null,
        nextFolderId: remaining[insertAt]?.id ?? null,
    };
}
