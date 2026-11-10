import { v4 as createOperationId } from "uuid";
import { useCallback, useState } from "react";
import { useMoveJobProgress } from "./useMoveJobProgress";

import {
  FileType,
  type InvalidEntry,
  type KnowledgeFile,
  precheckMoveFilesApi,
  confirmMoveFilesApi,
  type MovedEntry,
  type MoveResult,
} from "~/api/knowledge";
import { toast } from "@bisheng/ui";

import { useConfirm, useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";

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
 * single name clash names the conflicting folder. Order follows first appearance.
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
    .map(([label, names]) =>
      localize("com_knowledge.move_reason_group", {
        0: label,
        1: names.join("、"),
      }),
    )
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
 * handling cross-space confirmation (AC-18), the partial-conflict two-step (AC-14/15:
 * reject-all then offer "move the rest"), success/error toasts, and a refresh.
 *
 * Same-space undo (AC-16/17) reclassifies the inverse move and confirms its real plan.
 */
export function useKnowledgeMove({ spaceId, onMoved }: UseKnowledgeMoveArgs) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const confirm = useConfirm();
  const moveProgress = useMoveJobProgress(spaceId, onMoved, (entries) => {
    toast.success(
      localize("com_knowledge.move_success", { 0: entries.length }),
      {
        action: {
          label: localize("com_knowledge.move_undo"),
          onClick: () => {
            void undoMove(entries);
          },
        },
      },
    );
  });

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
   * move-the-rest and cancel actions; "move the rest" then opens the picker with only the
   * permitted items. The backend re-validates every item on the actual move.
   */
  const requestBatchMove = useCallback(
    async (
      permitted: KnowledgeFile[],
      denied: KnowledgeFile[],
      uploading: KnowledgeFile[] = [],
    ) => {
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
        parts.push(
          localize("com_knowledge.move_reason_group", {
            0: localize("com_knowledge.move_reason_uploading"),
            1: uploading.map((f) => f.name).join("、"),
          }),
        );
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
      if (code === 18040)
        return localize("com_knowledge.move_error_permission");
      if (code === 18041) return localize("com_knowledge.move_error_tenant");
      if (code === 18033) return localize("com_knowledge.move_error_target");
      return localize("com_knowledge.move_failed");
    },
    [localize],
  );

  const runMove = useCallback(
    async (
      items: KnowledgeFile[],
      targetSpaceId: string,
      targetFolderId: string | null,
    ): Promise<MoveResult | null> => {
      if (moveProgress.hasPendingConfirmation()) {
        moveProgress.recoverConfirmation();
        throw new Error("move:pending-confirmation");
      }
      const review = await precheckMoveFilesApi(spaceId, {
        items: items.map((file) => ({
          id: file.id,
          type: file.type === FileType.FOLDER ? "folder" : "file",
        })),
        target_space_id: targetSpaceId,
        target_folder_id: targetFolderId,
      });
      const plan = review.precheck;
      const invalid = plan.invalid_items.map((entry) => ({
        id: entry.id ?? 0,
        type: entry.type === "folder" ? ("folder" as const) : ("file" as const),
        name: entry.name ?? localize("com_knowledge.move_unavailable_item"),
        reason: entry.reason as InvalidEntry["reason"],
      }));
      const removed = Array.isArray(plan.impact.removed_fields)
        ? plan.impact.removed_fields.join(", ")
        : "";
      const description = [
        invalid.length ? describeInvalid(invalid, localize) : "",
        targetSpaceId !== spaceId
          ? localize("com_knowledge.move_review_impact", {
              0: plan.impact.logical_count ?? plan.valid_items.length,
              1: removed || localize("com_knowledge.move_no_removed_fields"),
            })
          : "",
      ]
        .filter(Boolean)
        .join("\n");
      if (invalid.length || targetSpaceId !== spaceId) {
        const ok = await confirm({
          title: localize("com_knowledge.move_review_title"),
          description,
          cancelText: localize("com_knowledge.move_cancel_all"),
          confirmText: localize("com_knowledge.move_here"),
        });
        if (!ok || !plan.can_execute) throw new Error("move:cancelled");
      }
      if (!plan.can_execute) throw new Error("move:unavailable");
      const key = createOperationId();
      moveProgress.remember(review, key);
      let result: Awaited<ReturnType<typeof confirmMoveFilesApi>>;
      try {
        result = await confirmMoveFilesApi(spaceId, review, key);
        moveProgress.clearConfirmation();
      } catch (error) {
        if ([18087, 18088].includes((error as { status_code?: number })?.status_code ?? 0))
          moveProgress.clearConfirmation();
        else moveProgress.recoverConfirmation();
        throw error;
      }
      if ("accepted" in result) {
        moveProgress.start(result, review.managementTenant);
        showToast({
          message: localize("com_knowledge.move_submitted"),
          status: "success",
        });
        return null;
      }
      return result;
    },
    [spaceId, confirm, localize, moveProgress, showToast],
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
          await runMove(
            items.map(
              (entry) =>
                ({
                  id: String(entry.id),
                  type:
                    entry.type === "folder" ? FileType.FOLDER : FileType.TXT,
                }) as KnowledgeFile,
            ),
            spaceId,
            parentId != null ? String(parentId) : null,
          );
        }
        showToast({
          message: localize("com_knowledge.move_undone"),
          status: "success",
        });
      } catch (err) {
        showToast({ message: resolveErrorMessage(err), status: "warning" });
      }
      onMoved();
    },
    [spaceId, showToast, localize, resolveErrorMessage, onMoved, runMove],
  );

  /**
   * Core move orchestration shared by the dialog and drag-drop entry points:
   * cross-space confirmation, partial-conflict two-step, success/error toast, refresh.
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
      let result: MoveResult | null;
      try {
        result = await runMove(items, targetSpaceId, targetFolderId);
      } catch (err) {
        if (!(err instanceof Error && err.message === "move:cancelled"))
          showToast({ message: resolveErrorMessage(err), status: "warning" });
        throw err;
      }
      if (!result) return;
      const movedCount = result.moved.length;
      const movedEntries = result.moved;
      onMoved();

      if (crossSpace) {
        showToast({
          message: localize("com_knowledge.move_cross_success", {
            0: movedCount,
          }),
          status: "success",
        });
      } else if (movedCount > 0) {
        // Same-space: success toast with an inline undo action.
        const message = targetFolderName
          ? localize("com_knowledge.move_undo_toast", { 0: targetFolderName })
          : localize("com_knowledge.move_success", { 0: movedCount });
        // The shared toast owns the action slot,
        // so the standalone undo toast is gone. Lifetime is doubled
        // automatically because there is an action button (§6).
        toast.success(message, {
          action: {
            label: localize("com_knowledge.move_undo"),
            onClick: () => {
              void undoMove(movedEntries);
            },
          },
        });
      }
    },
    [localize, runMove, showToast, resolveErrorMessage, onMoved, undoMove],
  );

  /** Dialog `onConfirm` — moves the items the picker was opened for. */
  const handleMoveConfirm = useCallback(
    (
      targetSpaceId: string,
      targetFolderId: string | null,
      crossSpace: boolean,
      targetFolderName?: string,
    ) =>
      executeMove(
        pendingItems,
        targetSpaceId,
        targetFolderId,
        crossSpace,
        targetFolderName,
      ),
    [executeMove, pendingItems],
  );

  /**
   * Drag-drop entry: move the dragged items into a folder in the SAME space.
   * Swallows the cancel/error rejection (no dialog to keep open).
   */
  const dropMoveToFolder = useCallback(
    async (
      items: KnowledgeFile[],
      targetFolderId: string,
      targetFolderName?: string,
    ) => {
      // Dropping onto a folder that is itself being dragged is a no-op.
      const filtered = items.filter((f) => f.id !== targetFolderId);
      if (!filtered.length) return;
      try {
        await executeMove(
          filtered,
          spaceId,
          targetFolderId,
          false,
          targetFolderName,
        );
      } catch {
        // Reason already surfaced via toast / confirm cancel.
      }
    },
    [executeMove, spaceId],
  );

  return {
    moveProgress,
    moveDialogOpen,
    setMoveDialogOpen,
    openMove,
    requestBatchMove,
    handleMoveConfirm,
    dropMoveToFolder,
  };
}
