import { useCallback, useState } from "react";

import { FileType, type KnowledgeFile, moveFilesApi, type MoveResult } from "~/api/knowledge";
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
            targetSpaceId: string,
            targetFolderId: string | null,
            skipInvalid: boolean,
        ): Promise<MoveResult> =>
            moveFilesApi(spaceId, {
                items: pendingItems.map((f) => ({
                    id: f.id,
                    type: f.type === FileType.FOLDER ? "folder" : "file",
                })),
                target_space_id: targetSpaceId,
                target_folder_id: targetFolderId,
                skip_invalid: skipInvalid,
            }),
        [spaceId, pendingItems],
    );

    /**
     * Dialog `onConfirm`. Throws to keep the dialog open (cancelled confirm /
     * hard error); resolves to let the dialog close on success.
     */
    const handleMoveConfirm = useCallback(
        async (targetSpaceId: string, targetFolderId: string | null, crossSpace: boolean) => {
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
                result = await runMove(targetSpaceId, targetFolderId, false);
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
                    result = await runMove(targetSpaceId, targetFolderId, true);
                } catch (err) {
                    showToast({ message: resolveErrorMessage(err), status: "error" });
                    throw err;
                }
            }

            const moved = result.moved.length;
            showToast({
                message: crossSpace
                    ? localize("com_knowledge.move_cross_success", { 0: moved })
                    : localize("com_knowledge.move_success", { 0: moved }),
                status: "success",
            });
            onMoved();
        },
        [confirm, localize, runMove, showToast, resolveErrorMessage, onMoved],
    );

    return { moveDialogOpen, setMoveDialogOpen, openMove, handleMoveConfirm };
}
