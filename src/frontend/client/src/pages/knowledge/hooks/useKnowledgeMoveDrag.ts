import { useRef, useState } from "react";

import { type KnowledgeFile } from "~/api/knowledge";
import { isKnowledgeItemUploading } from "../knowledgeUtils";

interface UseKnowledgeMoveDragArgs {
    /** Files currently rendered (used to expand the selection on drag). */
    files: KnowledgeFile[];
    /** Currently multi-selected file ids. */
    selectedFiles: Set<string>;
    /** Drop handler — undefined disables drag entirely (no move permission). */
    onMoveToFolder?: (folderId: string, items: KnowledgeFile[]) => void;
}

/**
 * Shared same-space drag-to-folder move wiring (F034), used by both the table
 * (FileTable) and card grid (FileCard) views. Rows/cards are drag sources;
 * folder rows/cards are drop targets that highlight while a valid drag hovers.
 *
 * Dragging an item that is part of the current multi-selection drags the whole
 * selection; otherwise just that one item.
 */
export function useKnowledgeMoveDrag({ files, selectedFiles, onMoveToFolder }: UseKnowledgeMoveDragArgs) {
    const enabled = !!onMoveToFolder;
    const dragItemsRef = useRef<KnowledgeFile[]>([]);
    const [dragOverFolderId, setDragOverFolderId] = useState<string | null>(null);

    const handleDragStart = (file: KnowledgeFile) => (e: React.DragEvent) => {
        const payload =
            selectedFiles.has(file.id) && selectedFiles.size > 0
                ? files.filter((f) => selectedFiles.has(f.id))
                : [file];
        // Uploading placeholders have no stable backend identity yet — if any
        // is in the payload (single or expanded selection), cancel the drag.
        if (payload.some(isKnowledgeItemUploading)) {
            e.preventDefault();
            return;
        }
        dragItemsRef.current = payload;
        e.dataTransfer.effectAllowed = "move";
        try {
            e.dataTransfer.setData("text/plain", payload.map((f) => f.id).join(","));
        } catch {
            // setData can throw in some browsers; payload already in the ref.
        }
    };

    const isDroppableFolder = (folder: KnowledgeFile) =>
        dragItemsRef.current.length > 0 && !dragItemsRef.current.some((f) => f.id === folder.id);

    const handleFolderDragOver = (folder: KnowledgeFile) => (e: React.DragEvent) => {
        if (!isDroppableFolder(folder)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (dragOverFolderId !== folder.id) setDragOverFolderId(folder.id);
    };

    const handleFolderDragLeave = (folder: KnowledgeFile) => () =>
        setDragOverFolderId((prev) => (prev === folder.id ? null : prev));

    const handleFolderDrop = (folder: KnowledgeFile) => (e: React.DragEvent) => {
        e.preventDefault();
        const items = dragItemsRef.current;
        dragItemsRef.current = [];
        setDragOverFolderId(null);
        if (items.length && onMoveToFolder) onMoveToFolder(folder.id, items);
    };

    return {
        enabled,
        dragOverFolderId,
        handleDragStart,
        handleFolderDragOver,
        handleFolderDragLeave,
        handleFolderDrop,
    };
}
