import { useCallback, useState } from "react";

import {
    FileType,
    type KnowledgeFile,
    moveFilesApi,
    type MovedEntry,
    type MoveResult,
} from "~/api/knowledge";
import { useConfirm, useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";

interface UseKnowledgeMoveArgs {
    /** Source space the selected items currently live in. */
    spaceId: string;
    /** Called after a successful move so the caller can refresh its file list. */
    onMoved: () => void;
}

/**
 * Orchestrates the "move files/folders" flow (F034) on top of {@link MoveToDialog}.
 *
 * Responsibilities: open the picker for a set of items; on confirm run the move,
 * handling cross-space二次确认 (AC-18), the partial-conflict two-step (AC-14/15:
 * reject-all then offer "move the rest"), success/error toasts, and a refresh.
 *
 * Same-space undo (AC-16/17) is intentionally not wired here — the toast channel
 * has no action button; tracked as a follow-up (see tasks deviation note).
 */
export function useKnowledgeMove({ spaceId, onMoved }: UseKnowledgeMoveArgs) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const confirm = useConfirm();

    const [moveDialogOpen, setMoveDialogOpen] = useState(false);
    const [pendingItems, setPendingItems] = useState<KnowledgeFile[]>([]);

    const openMove = useCallback((items: KnowledgeFile[]) => {
        if (!items.length) return;
        setPendingItems(items);
        setMoveDialogOpen(true);
    }, []);

    const resolveErrorMessage = useCallback(
        (err: unknown): string => {
            const code = (err as { status_code?: number })?.status_code;
            if (code === 18040) return localize("com_knowledge.move_error_permission");
            if (code === 18041) return localize("com_knowledge.move_error_tenant");
            if (code === 18033) return localize("com_knowledge.move_error_target");
            return localize("com_knowledge.move_failed");
        },
        [localize],
    );

    const runMove = useCallback(
        (
            items: KnowledgeFile[],
            targetSpaceId: string,
            targetFolderId: string | null,
            skipInvalid: boolean,
        ): Promise<MoveResult> =>
            moveFilesApi(spaceId, {
                items: items.map((f) => ({
                    id: f.id,
                    type: f.type === FileType.FOLDER ? "folder" : "file",
                })),
                target_space_id: targetSpaceId,
                target_folder_id: targetFolderId,
                skip_invalid: skipInvalid,
            }),
        [spaceId],
    );

    /**
     * Same-space undo (AC-16/17): move each item back to its original parent.
     * Items are grouped by `old_parent_id` since a batch may have come from
     * several folders; each group is restored to its own parent (root = null).
     */
    const undoMove = useCallback(
        async (moved: MovedEntry[]) => {
            const groups = new Map<number | null, MovedEntry[]>();
            for (const m of moved) {
                const list = groups.get(m.old_parent_id) ?? [];
                list.push(m);
                groups.set(m.old_parent_id, list);
            }
            try {
                for (const [parentId, items] of groups) {
                    await moveFilesApi(spaceId, {
                        items: items.map((m) => ({ id: String(m.id), type: m.type })),
                        target_space_id: spaceId,
                        target_folder_id: parentId != null ? String(parentId) : null,
                        skip_invalid: true,
                    });
                }
                showToast({ message: localize("com_knowledge.move_undone"), status: "success" });
            } catch (err) {
                showToast({ message: resolveErrorMessage(err), status: "error" });
            }
            onMoved();
        },
        [spaceId, showToast, localize, resolveErrorMessage, onMoved],
    );

    /**
     * Core move orchestration shared by the dialog and drag-drop entry points:
     * cross-space二次确认, partial-conflict two-step, success/error toast, refresh.
     * Throws on cancel/error so the dialog can stay open; drag callers swallow.
     */
    const executeMove = useCallback(
        async (
            items: KnowledgeFile[],
            targetSpaceId: string,
            targetFolderId: string | null,
            crossSpace: boolean,
        ) => {
            if (!items.length) return;
            if (crossSpace) {
                const ok = await confirm({
                    title: localize("com_knowledge.move_cross_space_confirm_title"),
                    description: localize("com_knowledge.move_cross_space_confirm_desc"),
                    cancelText: localize("cancel"),
                    confirmText: localize("com_knowledge.move_here"),
                });
                if (!ok) throw new Error("move:cancelled");
            }

            let result: MoveResult;
            try {
                result = await runMove(items, targetSpaceId, targetFolderId, false);
            } catch (err) {
                showToast({ message: resolveErrorMessage(err), status: "error" });
                throw err;
            }

            // Partial conflict: nothing was moved; offer to move only the valid ones.
            if (result.invalid.length > 0) {
                const names = result.invalid.map((i) => i.name).join("、");
                const ok = await confirm({
                    title: localize("com_knowledge.move_partial_title"),
                    description: localize("com_knowledge.move_partial_desc", { 0: names }),
                    cancelText: localize("com_knowledge.move_cancel_all"),
                    confirmText: localize("com_knowledge.move_rest"),
                });
                if (!ok) throw new Error("move:cancelled");
                try {
                    result = await runMove(items, targetSpaceId, targetFolderId, true);
                } catch (err) {
                    showToast({ message: resolveErrorMessage(err), status: "error" });
                    throw err;
                }
            }

            const movedCount = result.moved.length;
            const movedEntries = result.moved;
            onMoved();

            if (crossSpace) {
                showToast({
                    message: localize("com_knowledge.move_cross_success", { 0: movedCount }),
                    status: "success",
                });
            } else if (movedCount > 0) {
                // Same-space: offer an undo via a confirm dialog (toast has no action).
                const undo = await confirm({
                    title: localize("com_knowledge.move_success", { 0: movedCount }),
                    description: localize("com_knowledge.move_undo_hint"),
                    confirmText: localize("com_knowledge.move_undo"),
                    cancelText: localize("com_knowledge.move_close"),
                });
                if (undo) await undoMove(movedEntries);
            }
        },
        [confirm, localize, runMove, showToast, resolveErrorMessage, onMoved, undoMove],
    );

    /** Dialog `onConfirm` — moves the items the picker was opened for. */
    const handleMoveConfirm = useCallback(
        (targetSpaceId: string, targetFolderId: string | null, crossSpace: boolean) =>
            executeMove(pendingItems, targetSpaceId, targetFolderId, crossSpace),
        [executeMove, pendingItems],
    );

    /**
     * Drag-drop entry: move the dragged items into a folder in the SAME space.
     * Swallows the cancel/error rejection (no dialog to keep open).
     */
    const dropMoveToFolder = useCallback(
        async (items: KnowledgeFile[], targetFolderId: string) => {
            // Dropping onto a folder that is itself being dragged is a no-op.
            const filtered = items.filter((f) => f.id !== targetFolderId);
            if (!filtered.length) return;
            try {
                await executeMove(filtered, spaceId, targetFolderId, false);
            } catch {
                // Reason already surfaced via toast / confirm cancel.
            }
        },
        [executeMove, spaceId],
    );

    return { moveDialogOpen, setMoveDialogOpen, openMove, handleMoveConfirm, dropMoveToFolder };
}
