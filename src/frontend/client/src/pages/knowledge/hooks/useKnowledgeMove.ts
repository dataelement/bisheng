import { useCallback, useState } from "react";

import {
    FileType,
    type InvalidEntry,
    type KnowledgeFile,
    moveFilesApi,
    type MovedEntry,
    type MoveResult,
} from "~/api/knowledge";
import { useConfirm, useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";

import { showMoveUndoToast } from "../components/moveUndoToast";

type Localize = ReturnType<typeof useLocalize>;

/** i18n key for a per-item rejection reason (name_conflict differs by item type). */
function reasonLabelKey(entry: InvalidEntry): string {
    if (entry.reason === "name_conflict") {
        return entry.type === "folder"
            ? "com_knowledge.move_reason_name_conflict_folder"
            : "com_knowledge.move_reason_name_conflict_file";
    }
    return `com_knowledge.move_reason_${entry.reason}`;
}

/**
 * Build a human description of why items were rejected, grouped by reason so a
 * single name-clash reads "目标位置已存在同名文件夹：a" instead of the generic
 * "部分项无法移动：a". Order follows first appearance.
 */
function describeInvalid(invalid: InvalidEntry[], localize: Localize): string {
    const groups = new Map<string, string[]>();
    for (const entry of invalid) {
        const label = localize(reasonLabelKey(entry));
        const names = groups.get(label) ?? [];
        names.push(entry.name);
        groups.set(label, names);
    }
    return Array.from(groups.entries())
        .map(([label, names]) => localize("com_knowledge.move_reason_group", { 0: label, 1: names.join("、") }))
        .join("\n");
}

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

    /**
     * Batch-move entry from the toolbar. `denied` = selected items the user lacks
     * move permission for (decided up-front on the frontend, space-level);
     * `uploading` = selected items still uploading (no backend id yet). If any of
     * either exist, show the block dialog listing them by reason with
     * 【移动其余文件】【取消移动】; "move the rest" then opens the picker with only the
     * permitted items. The backend re-validates every item on the actual move.
     */
    const requestBatchMove = useCallback(
        async (permitted: KnowledgeFile[], denied: KnowledgeFile[], uploading: KnowledgeFile[] = []) => {
            if (denied.length === 0 && uploading.length === 0) {
                openMove(permitted);
                return;
            }
            const parts: string[] = [];
            if (denied.length > 0) {
                const blocked: InvalidEntry[] = denied.map((f) => ({
                    id: Number(f.id),
                    type: f.type === FileType.FOLDER ? "folder" : "file",
                    name: f.name,
                    reason: "no_permission",
                }));
                parts.push(describeInvalid(blocked, localize));
            }
            if (uploading.length > 0) {
                // "uploading" is a frontend-only reason (not a backend MoveInvalidReason),
                // so render its group line directly instead of via describeInvalid.
                parts.push(localize("com_knowledge.move_reason_group", {
                    0: localize("com_knowledge.move_reason_uploading"),
                    1: uploading.map((f) => f.name).join("、"),
                }));
            }
            const ok = await confirm({
                title: localize("com_knowledge.move_partial_title"),
                description: parts.join("\n"),
                cancelText: localize("com_knowledge.move_cancel_all"),
                confirmText: localize("com_knowledge.move_rest"),
            });
            if (!ok || !permitted.length) return;
            openMove(permitted);
        },
        [confirm, localize, openMove],
    );

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
            targetFolderName?: string,
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

            // Some items were rejected; nothing was moved yet (reject-all). Always
            // a dialog listing the blocked items by reason + 【移动其余文件】【取消移动】
            // (even when ALL are blocked — "移动其余" then simply moves nothing).
            if (result.invalid.length > 0) {
                const ok = await confirm({
                    title: localize("com_knowledge.move_partial_title"),
                    description: describeInvalid(result.invalid, localize),
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
                // Same-space: success toast with an inline 「撤回」 action.
                const message = targetFolderName
                    ? localize("com_knowledge.move_undo_toast", { 0: targetFolderName })
                    : localize("com_knowledge.move_success", { 0: movedCount });
                showMoveUndoToast({
                    message,
                    actionLabel: localize("com_knowledge.move_undo"),
                    onAction: () => {
                        void undoMove(movedEntries);
                    },
                });
            }
        },
        [confirm, localize, runMove, showToast, resolveErrorMessage, onMoved, undoMove],
    );

    /** Dialog `onConfirm` — moves the items the picker was opened for. */
    const handleMoveConfirm = useCallback(
        (targetSpaceId: string, targetFolderId: string | null, crossSpace: boolean, targetFolderName?: string) =>
            executeMove(pendingItems, targetSpaceId, targetFolderId, crossSpace, targetFolderName),
        [executeMove, pendingItems],
    );

    /**
     * Drag-drop entry: move the dragged items into a folder in the SAME space.
     * Swallows the cancel/error rejection (no dialog to keep open).
     */
    const dropMoveToFolder = useCallback(
        async (items: KnowledgeFile[], targetFolderId: string, targetFolderName?: string) => {
            // Dropping onto a folder that is itself being dragged is a no-op.
            const filtered = items.filter((f) => f.id !== targetFolderId);
            if (!filtered.length) return;
            try {
                await executeMove(filtered, spaceId, targetFolderId, false, targetFolderName);
            } catch {
                // Reason already surfaced via toast / confirm cancel.
            }
        },
        [executeMove, spaceId],
    );

    return { moveDialogOpen, setMoveDialogOpen, openMove, requestBatchMove, handleMoveConfirm, dropMoveToFolder };
}
