import type { UseKnowledgeSpaceHeaderOptions } from "./knowledgeSpaceTypes";
import { useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { KnowledgeFile, SpaceRole, VisibilityType } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { buildClientShareUrl } from "~/components/CopyShareLinkButton";
import {
  hasKnowledgeSpaceAction,
  useKnowledgeSpaceActions,
} from "../hooks/useKnowledgeSpacePermissions";
import { useVersionManagementEnabled } from "~/hooks";
export function useKnowledgeSpaceHeader({
  selectedFiles,
  space,
  onDeleteFile,
  localize,
  showToast,
}: UseKnowledgeSpaceHeaderOptions) {
  const isAdmin =
    space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
  const { actions: spaceActions, ensureSpaceActions } =
    useKnowledgeSpaceActions([space.id]);
  useEffect(() => {
    void ensureSpaceActions(space.id);
  }, [ensureSpaceActions, space.id]);
  const canShareSpace = hasKnowledgeSpaceAction(
    spaceActions,
    space.id,
    "share",
  );
  const canDeleteSpace = hasKnowledgeSpaceAction(
    spaceActions,
    space.id,
    "delete",
  );
  const canManageMembers = hasKnowledgeSpaceAction(
    spaceActions,
    space.id,
    "manage_permission",
  );
  const canEditSpace = hasKnowledgeSpaceAction(spaceActions, space.id, "edit");
  // "Leave" is the joined-space counterpart of "delete", mirroring the space list's
  // rule (delete when you may, otherwise exit for spaces you joined). Department
  // spaces are membership-managed elsewhere, and a creator never leaves their own.
  const canLeaveSpace =
    !canDeleteSpace &&
    space.spaceKind !== "department" &&
    space.role !== SpaceRole.CREATOR;
  // ─── Version Management ──────────────────────────────────────────────
  const versionManagementEnabled = useVersionManagementEnabled();
  const queryClient = useQueryClient();
  const spaceIdNum = Number(space.id);

  const [versionMgmtFile, setVersionMgmtFile] = useState<KnowledgeFile | null>(
    null,
  );
  const [versionHistoryFile, setVersionHistoryFile] =
    useState<KnowledgeFile | null>(null);
  const [similarDialogOpen, setSimilarDialogOpen] = useState(false);
  // File ids (KnowledgeFile.id) the similar-document dialog is scoped to — snapshotted

  const [similarRestrictIds, setSimilarRestrictIds] = useState<string[]>([]);

  // Open the similar-document dialog scoped to the currently selected files.
  const handleProcessSimilar = () => {
    setSimilarRestrictIds(Array.from(selectedFiles));
    setSimilarDialogOpen(true);
  };

  // Invalidate pending-similar and trigger file list refresh after any version action.
  const handleVersionAction = () => {
    queryClient.invalidateQueries({
      queryKey: ["pending-similar", spaceIdNum],
    });
    queryClient.invalidateQueries({ queryKey: ["file-versions"] });
    // Signal parent to reload file list (same pattern used by batch delete/retry).
    onDeleteFile("");
  };

  // Share = copy the space share link (mirrors the desktop CopyShareLinkButton);
  // only when the space is shareable and not private.
  const showShareInMenu =
    canShareSpace && space.visibility !== VisibilityType.PRIVATE;
  const handleCopyShareLink = async () => {
    try {
      await navigator.clipboard.writeText(
        buildClientShareUrl(`/knowledge/share/${space.id}`),
      );
      showToast({
        message: localize("com_knowledge.share_link_copied"),
        severity: NotificationSeverity.SUCCESS,
      });
    } catch {
      showToast({
        message: localize("com_knowledge.share_link_copy_failed"),
        severity: NotificationSeverity.WARNING,
      });
    }
  };

  return {
    isAdmin,
    ensureSpaceActions,
    canShareSpace,
    canDeleteSpace,
    canManageMembers,
    canEditSpace,
    canLeaveSpace,
    versionManagementEnabled,
    queryClient,
    spaceIdNum,
    versionMgmtFile,
    setVersionMgmtFile,
    versionHistoryFile,
    setVersionHistoryFile,
    similarDialogOpen,
    setSimilarDialogOpen,
    similarRestrictIds,
    setSimilarRestrictIds,
    handleProcessSimilar,
    handleVersionAction,
    showShareInMenu,
    handleCopyShareLink,
  };
}
